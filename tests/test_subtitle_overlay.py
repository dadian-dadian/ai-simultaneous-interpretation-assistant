import threading
import unittest
from time import perf_counter

from PySide6.QtCore import Qt, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.core.config import AppConfig
from app.core.recognition_profile import get_recognition_profile
from app.core.subtitle import SubtitleEvent, SubtitleSegmentStatus
from app.translate import TranslationUpdate
from app.ui.main_window import MainWindow
from app.ui.subtitle_overlay import SubtitleOverlayWindow


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def close_top_level_widgets(app: QApplication) -> None:
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()


class _CaptureTranslationManager:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def submit(self, **kwargs: object) -> None:
        self.requests.append(kwargs)

    def stop(self) -> None:
        return


class SubtitleOverlayWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = get_qapp()

    def tearDown(self) -> None:
        close_top_level_widgets(self.app)

    def test_caption_text_can_be_updated(self) -> None:
        overlay = SubtitleOverlayWindow()

        overlay.set_caption("hello", "你好", "updated")

        self.assertEqual(overlay.source_label.text(), "hello")
        self.assertEqual(overlay.translation_label.text(), "你好")
        self.assertEqual(overlay.state_badge.text(), "已修正")

    def test_two_chinese_sentences_use_independent_display_slots(self) -> None:
        overlay = SubtitleOverlayWindow()

        overlay.set_caption(
            "English source",
            "第一句已经稳定。\n第二句仍在更新",
            "finalizing",
        )

        self.assertEqual(overlay.translation_stable_label.text(), "第一句已经稳定。")
        self.assertEqual(overlay.translation_label.text(), "第二句仍在更新")
        self.assertEqual(overlay.state_badge.text(), "确认中")
        self.assertEqual(
            overlay.translation_stable_label.font().pointSize(),
            overlay.translation_label.font().pointSize(),
        )
        self.assertFalse(overlay.source_label.wordWrap())

    def test_chinese_labels_remove_stray_spaces_and_use_compact_spacing(self) -> None:
        overlay = SubtitleOverlayWindow()
        overlay.resize(680, 220)
        overlay.show()

        overlay.set_caption(
            "English source",
            " 第一句 。\n第二 句。\n让我们开始  ——  什么 是财富",
            "partial",
        )
        self.app.processEvents()

        visible_labels = [
            label
            for label in overlay._sentence_labels
            if label.isVisible()
        ]
        self.assertEqual(
            [label.text() for label in visible_labels],
            ["第一句。", "第二句。", "让我们开始——什么是财富"],
        )
        self.assertEqual(overlay.translation_layout.spacing(), 2)
        for previous, current in zip(
            visible_labels,
            visible_labels[1:],
            strict=False,
        ):
            self.assertEqual(
                current.y() - (previous.y() + previous.height()),
                2,
            )
        overlay.close()

    def test_four_chinese_sentences_use_independent_display_slots(self) -> None:
        overlay = SubtitleOverlayWindow()

        overlay.set_caption(
            "Current English source",
            "第一句。\n第二句。\n第三句。\n第四句正在更新",
            "partial",
        )

        completed = [
            label.text()
            for label in overlay.completed_labels
            if label.text()
        ]
        self.assertEqual(completed, ["第一句。", "第二句。", "第三句。"])
        self.assertEqual(overlay.translation_label.text(), "第四句正在更新")
        self.assertFalse(
            bool(overlay.translation_label.property("captionCompleted"))
        )

    def test_fifth_sentence_rolls_window_without_recreating_completed_labels(
        self,
    ) -> None:
        overlay = SubtitleOverlayWindow()
        overlay.set_caption(
            "Current English source",
            "第一句。\n第二句。\n第三句。\n第四句。",
            "partial",
        )
        sentence_label_ids = [id(label) for label in overlay._sentence_labels]
        rollover_count = overlay.translation_label._rollover_count

        overlay.set_caption(
            "New English source",
            "第二句。\n第三句。\n第四句。\n第五句正在更新",
            "partial",
        )

        self.assertEqual(
            [label.text() for label in overlay.completed_labels],
            ["第二句。", "第三句。", "第四句。"],
        )
        self.assertEqual(overlay.translation_label.text(), "第五句正在更新")
        self.assertEqual(
            [id(label) for label in overlay._sentence_labels],
            sentence_label_ids,
        )
        self.assertEqual(
            overlay.translation_label._rollover_count,
            rollover_count + 1,
        )

    def test_chinese_viewport_wraps_long_sentence_and_scrolls_to_bottom(self) -> None:
        overlay = SubtitleOverlayWindow()
        overlay.resize(500, 150)
        overlay.show()
        long_sentence = "这是一段很长的中文字幕内容" * 12

        overlay.set_caption(
            "English source",
            f"第一句已经完成。第二句已经完成。{long_sentence}",
            "partial",
        )
        self.app.processEvents()
        QTest.qWait(180)

        self.assertGreater(
            overlay.translation_label.height(),
            overlay.translation_label.fontMetrics().height(),
        )
        scrollbar = overlay.translation_scroll.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        self.assertEqual(scrollbar.value(), scrollbar.maximum())
        overlay.close()

    def test_panel_height_controls_visible_area_without_sentence_count_cap(self) -> None:
        overlay = SubtitleOverlayWindow()
        overlay.resize(680, 420)
        overlay.show()
        chinese = "".join(f"这是第{index}句。" for index in range(12))

        overlay.set_caption("English source", chinese, "final")
        self.app.processEvents()

        visible_texts = [
            label.text()
            for label in overlay._sentence_labels
            if not label.isHidden()
        ]
        self.assertEqual(visible_texts, [chinese])
        self.assertEqual(overlay.height(), 420)
        overlay.close()

    def test_punctuation_does_not_split_preview_into_extra_labels(self) -> None:
        overlay = SubtitleOverlayWindow()

        text = "第一句已经完成。第二句继续出现。第三句仍然留在同一个预览块里。"
        overlay.set_caption("English source", text, "partial")

        visible_texts = [
            label.text()
            for label in overlay._sentence_labels
            if not label.isHidden()
        ]
        self.assertEqual(visible_texts, [text])
        self.assertEqual(overlay.translation_label.text(), text)
        overlay.close()

    def test_resize_does_not_leave_hidden_translation_label_gap(self) -> None:
        overlay = SubtitleOverlayWindow()
        overlay.resize(520, 180)
        overlay.show()
        overlay.set_caption("English source", "第一句。\n第二句。\n第三句。", "partial")
        self.app.processEvents()

        text = "这是一个很长的中文字幕预览块。它不应该因为标点被拆成很多行。"
        overlay.set_caption("English source", text, "partial")
        overlay.resize(920, 180)
        self.app.processEvents()
        QTest.qWait(20)

        visible_labels = [
            label
            for label in overlay._sentence_labels
            if label.isVisible()
        ]
        hidden_heights = [
            label.height()
            for label in overlay._sentence_labels
            if not label.isVisible()
        ]
        self.assertEqual([label.text() for label in visible_labels], [text])
        self.assertTrue(all(height == 0 for height in hidden_heights))
        self.assertLessEqual(
            overlay.translation_content.minimumHeight(),
            visible_labels[0].height(),
        )
        overlay.close()

    def test_resize_remeasures_wrapped_translation_height_after_expanding(self) -> None:
        overlay = SubtitleOverlayWindow()
        overlay.resize(500, 170)
        overlay.show()
        text = "杩欐槸涓€娈甸渶瑕佸湪绐勭獥鍙ｄ腑鎹㈡垚寰堝琛岀殑涓枃瀛楀箷" * 8

        overlay.set_caption("English source", text, "partial")
        self.app.processEvents()
        QTest.qWait(90)
        narrow_height = overlay.translation_label.height()

        overlay.resize(1100, 170)
        self.app.processEvents()
        QTest.qWait(120)

        wide_height = overlay.translation_label.height()
        self.assertLess(wide_height, narrow_height)
        self.assertEqual(overlay.translation_content.minimumHeight(), wide_height)
        overlay.close()

    def test_english_footer_stays_single_line_and_scrolls_horizontally(self) -> None:
        overlay = SubtitleOverlayWindow()
        overlay.resize(500, 180)
        overlay.show()
        english = " ".join(["real-time English source keeps growing"] * 12)

        overlay.set_caption(english, "当前中文字幕", "partial")
        self.app.processEvents()
        QTest.qWait(160)

        scrollbar = overlay.source_scroll.horizontalScrollBar()
        self.assertFalse(overlay.source_label.wordWrap())
        self.assertGreater(scrollbar.maximum(), 0)
        self.assertEqual(scrollbar.value(), scrollbar.maximum())
        self.assertFalse(overlay.divider.isHidden())
        overlay.close()

    def test_high_frequency_partial_updates_reuse_widgets(self) -> None:
        overlay = SubtitleOverlayWindow()
        overlay.resize(680, 220)
        overlay.show()
        started_at = perf_counter()

        for index in range(500):
            active = "当前长句正在持续加载" + ("内容" * (index % 45))
            overlay.set_caption(
                "live English source " + ("word " * (index % 30)),
                f"第一句完成。第二句完成。{active}",
                "partial",
            )
            if index % 25 == 0:
                self.app.processEvents()
        self.app.processEvents()
        elapsed = perf_counter() - started_at

        self.assertLessEqual(len(overlay._sentence_labels), 4)
        self.assertLess(elapsed, 1.5)
        overlay.close()

    def test_display_mode_controls_visible_labels(self) -> None:
        overlay = SubtitleOverlayWindow()

        overlay.set_display_mode("zh")
        self.assertFalse(overlay.translation_label.isHidden())
        self.assertTrue(overlay.source_label.isHidden())

        overlay.set_display_mode("source")
        self.assertTrue(overlay.translation_label.isHidden())
        self.assertFalse(overlay.source_label.isHidden())

    def test_bilingual_mode_does_not_duplicate_untranslated_source(self) -> None:
        overlay = SubtitleOverlayWindow()

        overlay.set_display_mode("bilingual")
        overlay.set_caption("live English caption", "live English caption")

        self.assertFalse(overlay.translation_label.isHidden())
        self.assertEqual(overlay.translation_label.text(), "")
        self.assertFalse(overlay.source_label.isHidden())
        self.assertEqual(overlay.source_label.text(), "live English caption")

    def test_source_caption_is_visually_secondary(self) -> None:
        overlay = SubtitleOverlayWindow()

        overlay.set_font_size(18)

        self.assertEqual(overlay.translation_label.font().pointSize(), 18)
        self.assertGreaterEqual(overlay.source_label.font().pointSize(), 8)
        self.assertLessEqual(overlay.source_label.font().pointSize(), 9)
        self.assertLess(
            overlay.source_label.font().pointSize(),
            overlay.translation_label.font().pointSize(),
        )

    def test_overlay_defaults_to_a_compact_caption_ribbon(self) -> None:
        overlay = SubtitleOverlayWindow()

        self.assertEqual((overlay.width(), overlay.height()), (680, 190))
        self.assertEqual(overlay.translation_label.font().pointSize(), 14)
        self.assertGreaterEqual(overlay.source_label.font().pointSize(), 8)
        self.assertLessEqual(overlay.source_label.font().pointSize(), 9)
        self.assertEqual(
            overlay.translation_stable_label.font().pointSize(),
            overlay.translation_label.font().pointSize(),
        )
        self.assertTrue(overlay.header.isHidden())
        self.assertTrue(overlay.resize_grip.isHidden())
        self.assertEqual(overlay.maximumHeight(), 16_777_215)
        self.assertGreater(overlay.translation_label.maximumHeight(), 1_000)

    def test_overlay_size_presets_and_manual_resize_are_available(self) -> None:
        overlay = SubtitleOverlayWindow()

        overlay.set_size_preset("wide")
        self.assertEqual((overlay.width(), overlay.height()), (1080, 260))

        overlay.resize(740, 162)
        self.assertEqual((overlay.width(), overlay.height()), (740, 162))
        self.assertEqual((overlay.minimumWidth(), overlay.minimumHeight()), (480, 140))

    def test_opacity_is_clamped(self) -> None:
        overlay = SubtitleOverlayWindow()

        overlay.set_opacity_percent(10)
        self.assertEqual(overlay.windowOpacity(), 0.4)

        overlay.set_opacity_percent(120)
        self.assertEqual(overlay.windowOpacity(), 1.0)


class MainWindowOverlayIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = get_qapp()

    def tearDown(self) -> None:
        close_top_level_widgets(self.app)

    def test_main_window_creates_overlay_window(self) -> None:
        window = MainWindow(AppConfig())

        self.assertIsInstance(window.overlay, SubtitleOverlayWindow)
        self.assertFalse(window.overlay.isVisible())

        window._show_overlay()
        self.assertTrue(window.overlay.isVisible())

        window._hide_overlay()
        self.assertFalse(window.overlay.isVisible())

    def test_main_window_maps_recognition_mode_buttons(self) -> None:
        window = MainWindow(AppConfig())

        window.recognition_mode_buttons[2].setChecked(True)
        profile = window._selected_recognition_profile()

        self.assertEqual(profile.mode, "high-accuracy")
        self.assertEqual(profile.queue_size, 64)

    def test_main_window_controls_overlay_size_presets(self) -> None:
        window = MainWindow(AppConfig())

        self.assertEqual(window.overlay_size_combo.currentIndex(), 0)
        self.assertEqual((window.overlay.width(), window.overlay.height()), (680, 190))

        window.overlay_size_combo.setCurrentIndex(1)

        self.assertEqual((window.overlay.width(), window.overlay.height()), (860, 260))

        window._show_overlay()
        window.overlay.resize(740, 162)
        self.app.processEvents()

        self.assertEqual(window.overlay_size_combo.currentText(), "自定义")

    def test_overlay_close_button_updates_main_window_toggle(self) -> None:
        window = MainWindow(AppConfig())
        window._show_overlay()

        window.overlay.close_button.click()
        self.app.processEvents()

        self.assertFalse(window.overlay.isVisible())
        self.assertFalse(window.overlay_toggle.isChecked())

    def test_main_window_shows_dropped_chunks_warning(self) -> None:
        window = MainWindow(AppConfig())
        window._active_recognition_profile = get_recognition_profile("balanced")

        window._handle_dropped_chunks_changed(8)

        self.assertEqual(window.dropped_chunks_label.text(), "丢帧：8")
        self.assertIn("识别处理可能跟不上", window.correction_hint_label.text())

    def test_stale_realtime_worker_events_are_ignored(self) -> None:
        window = MainWindow(AppConfig())
        window._realtime_generation = 2
        window._accept_realtime_generation = 2

        window._handle_realtime_subtitle_event_for_generation(
            1,
            SubtitleEvent.partial("asr_old_s0001", "old source", "old source"),
        )
        self.assertIsNone(window.subtitle_state.get("asr_old_s0001"))

        window._handle_realtime_subtitle_event_for_generation(
            2,
            SubtitleEvent.partial("asr_live_s0001", "live source", "live source"),
        )
        self.assertIsNotNone(window.subtitle_state.get("asr_live_s0001"))

        window._accept_realtime_generation = None
        window._handle_realtime_subtitle_event_for_generation(
            2,
            SubtitleEvent.partial("asr_late_s0001", "late source", "late source"),
        )
        self.assertIsNone(window.subtitle_state.get("asr_late_s0001"))

    def test_realtime_relay_runs_ui_handler_on_qt_main_thread(self) -> None:
        window = MainWindow(AppConfig())
        window._realtime_generation = 3
        window._accept_realtime_generation = 3
        completed = threading.Event()
        ran_on_main_thread: list[bool] = []

        def capture_ui_handler(event: SubtitleEvent) -> None:
            del event
            ran_on_main_thread.append(QThread.currentThread() == self.app.thread())
            completed.set()

        window._handle_realtime_subtitle_event = capture_ui_handler  # type: ignore[method-assign]

        thread = threading.Thread(
            target=lambda: window.realtime_subtitle_event.emit(
                3,
                SubtitleEvent.partial("asr_thread_s0001", "source", "source"),
            )
        )
        thread.start()
        thread.join(timeout=2.0)

        for _ in range(50):
            self.app.processEvents()
            if completed.is_set():
                break
            QTest.qWait(10)

        self.assertTrue(completed.is_set())
        self.assertEqual(ran_on_main_thread, [True])

    def test_main_window_advances_demo_stream_once(self) -> None:
        window = MainWindow(AppConfig())

        window._advance_demo_stream()
        window.demo_timer.stop()

        segment = window.subtitle_state.get("seg_001")
        self.assertIsNotNone(segment)
        assert segment is not None
        self.assertEqual(segment.status, SubtitleSegmentStatus.PARTIAL)
        self.assertIn("Transformer", window.translation_caption_label.text())
        self.assertEqual(window.history_list.count(), 1)

    def test_realtime_caption_limits_long_partial_without_truncating_history(self) -> None:
        window = MainWindow(AppConfig())
        words = (
            "today we're testing a real-time English subtitle system the speaker is talking "
            "quickly moving from one idea to the next and leaving only short pauses"
        ).split()

        for index in range(1, len(words) + 1):
            text = " ".join(words[:index])
            window._handle_realtime_subtitle_event(
                SubtitleEvent.partial("asr_0001", text, text)
            )
        window._flush_realtime_render()

        display_text = window.source_caption_label.text()
        history_text = window.history_list.item(0).text()
        self.assertLessEqual(len(display_text.splitlines()), 1)
        self.assertIn("only short", display_text)
        self.assertIn("today we're testing", history_text)
        self.assertIn("short pauses", history_text)
        self.assertTrue(window.source_caption_label.isHidden())
        self.assertTrue(window.translation_caption_label.isHidden())
        self.assertEqual(window.translation_caption_label.text(), "")

    def test_main_window_uses_sidebar_and_history_without_live_caption_or_bottom_bar(
        self,
    ) -> None:
        window = MainWindow(AppConfig())

        self.assertIsNotNone(window.findChild(QWidget, "HistoryPanel"))
        self.assertIsNone(window.findChild(QWidget, "LiveCaption"))
        self.assertIsNone(window.findChild(QWidget, "BottomBar"))
        self.assertTrue(
            bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        )

    def test_realtime_sentence_partial_keeps_previous_final_as_context(self) -> None:
        window = MainWindow(AppConfig())
        window._handle_realtime_subtitle_event(
            SubtitleEvent.final("asr_0001_s0001", "I loved that job.", "I loved that job.")
        )
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial("asr_0001_s0002", "And I", "And I")
        )
        window._flush_realtime_render()

        self.assertEqual(
            window.source_caption_label.text(),
            "And I",
        )
        self.assertEqual(window.history_list.count(), 2)

    def test_translation_update_replaces_realtime_source_placeholder(self) -> None:
        window = MainWindow(AppConfig())
        window._handle_realtime_subtitle_event(
            SubtitleEvent.final("asr_0001_s0001", "I loved that job.", "I loved that job.")
        )
        segment = window.subtitle_state.get("asr_0001_s0001")
        self.assertIsNotNone(segment)
        assert segment is not None

        window._handle_translation_update(
            TranslationUpdate(
                segment_id=segment.segment_id,
                source_version=segment.version,
                source_text=segment.source_text,
                translated_text="我喜欢那份工作。",
                source_language="en",
                target_language="zh-CN",
                provider="baidu-mt",
                is_final=True,
            )
        )

        self.assertEqual(window.translation_caption_label.text(), "我喜欢那份工作。")
        self.assertIn("I loved that job.", window.source_caption_label.text())
        self.assertIn("我喜欢那份工作。", window.history_list.item(0).text())

    def test_stale_translation_update_is_ignored(self) -> None:
        window = MainWindow(AppConfig())
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial("asr_0001_s0001", "I loved that", "I loved that")
        )
        segment = window.subtitle_state.get("asr_0001_s0001")
        self.assertIsNotNone(segment)
        assert segment is not None
        stale_version = segment.version

        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial(
                "asr_0001_s0001",
                "I loved that job",
                "I loved that job",
            )
        )
        window._flush_realtime_render()
        window._handle_translation_update(
            TranslationUpdate(
                segment_id=segment.segment_id,
                source_version=stale_version,
                source_text="I loved that",
                translated_text="我喜欢那个。",
                source_language="en",
                target_language="zh-CN",
                provider="baidu-mt",
                is_final=False,
            )
        )

        self.assertEqual(window.translation_caption_label.text(), "")

    def test_long_partial_translation_submits_stable_prefix(self) -> None:
        window = MainWindow(AppConfig())
        manager = _CaptureTranslationManager()
        window.translation_manager = manager
        words = (
            "one two three four five six seven eight nine ten eleven twelve thirteen"
        )

        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial(
                "asr_0001_s0001",
                "one two three four five six seven eight nine ten eleven twelve",
                "one two three four five six seven eight nine ten eleven twelve",
            )
        )
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial("asr_0001_s0001", words, words)
        )

        self.assertEqual(len(manager.requests), 1)
        self.assertEqual(
            manager.requests[0]["source_text"],
            "one two three four five six seven eight nine ten eleven twelve",
        )
        self.assertTrue(manager.requests[0]["allow_source_prefix"])

    def test_prefix_translation_can_update_after_source_keeps_growing(self) -> None:
        window = MainWindow(AppConfig())
        first_text = (
            "one two three four five six seven eight nine ten eleven twelve"
        )
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial("asr_0001_s0001", first_text, first_text)
        )
        segment = window.subtitle_state.get("asr_0001_s0001")
        self.assertIsNotNone(segment)
        assert segment is not None
        prefix_version = segment.version
        prefix_text = "one two three four five six seven eight"

        grown_text = (
            "one two three four five six seven eight nine ten eleven twelve "
            "thirteen fourteen"
        )
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial("asr_0001_s0001", grown_text, grown_text)
        )
        window._flush_realtime_render()
        window._handle_translation_update(
            TranslationUpdate(
                segment_id="asr_0001_s0001",
                source_version=prefix_version,
                source_text=prefix_text,
                translated_text="ZH stable prefix",
                source_language="en",
                target_language="zh-CN",
                provider="baidu-mt",
                is_final=False,
                allow_source_prefix=True,
            )
        )

        self.assertEqual(window.translation_caption_label.text(), "ZH stable prefix")
        history_text = window.history_list.item(0).text()
        self.assertIn(prefix_text, history_text)
        self.assertNotIn("thirteen fourteen\nZH stable prefix", history_text)

    def test_visible_translation_survives_asr_source_revision(self) -> None:
        window = MainWindow(AppConfig())
        source_text = (
            "one two three four five six seven eight nine ten eleven twelve"
        )
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial("asr_0001_s0001", source_text, source_text)
        )
        segment = window.subtitle_state.get("asr_0001_s0001")
        self.assertIsNotNone(segment)
        assert segment is not None
        window._handle_translation_update(
            TranslationUpdate(
                segment_id="asr_0001_s0001",
                source_version=segment.version,
                source_text="one two three four five six seven eight",
                translated_text="ZH stable prefix",
                source_language="en",
                target_language="zh-CN",
                provider="baidu-mt",
                is_final=False,
                allow_source_prefix=True,
            )
        )

        revised_text = (
            "well one two three four five six seven eight nine ten eleven twelve"
        )
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial("asr_0001_s0001", revised_text, revised_text)
        )
        window._flush_realtime_render()

        self.assertEqual(window.translation_caption_label.text(), "ZH stable prefix")
        self.assertEqual(window.overlay.translation_label.text(), "ZH stable prefix")

    def test_shorter_prefix_translation_does_not_overwrite_longer_prefix(
        self,
    ) -> None:
        window = MainWindow(AppConfig())
        source_text = (
            "one two three four five six seven eight nine ten eleven twelve"
        )
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial("asr_0001_s0001", source_text, source_text)
        )
        segment = window.subtitle_state.get("asr_0001_s0001")
        self.assertIsNotNone(segment)
        assert segment is not None
        window._handle_translation_update(
            TranslationUpdate(
                segment_id="asr_0001_s0001",
                source_version=segment.version,
                source_text="one two three four five six seven eight nine ten",
                translated_text="ZH longer prefix",
                source_language="en",
                target_language="zh-CN",
                provider="baidu-mt",
                is_final=False,
                allow_source_prefix=True,
            )
        )
        window._handle_translation_update(
            TranslationUpdate(
                segment_id="asr_0001_s0001",
                source_version=segment.version,
                source_text="one two three four five six seven eight",
                translated_text="ZH shorter prefix",
                source_language="en",
                target_language="zh-CN",
                provider="baidu-mt",
                is_final=False,
                allow_source_prefix=True,
            )
        )

        self.assertEqual(window.translation_caption_label.text(), "ZH longer prefix")

    def test_realtime_partial_preserves_previous_translation_while_source_grows(
        self,
    ) -> None:
        window = MainWindow(AppConfig())
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial(
                "asr_0001_s0001",
                "I loved that job",
                "我喜欢那份工作",
            )
        )
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial(
                "asr_0001_s0001",
                "I loved that job very much",
                "I loved that job very much",
            )
        )
        window._flush_realtime_render()

        self.assertEqual(window.translation_caption_label.text(), "我喜欢那份工作")

    def test_old_translation_update_does_not_rewind_overlay_source(self) -> None:
        window = MainWindow(AppConfig())
        window._handle_realtime_subtitle_event(
            SubtitleEvent.final(
                "asr_0001_s0001",
                "First confirmed source.",
                "First confirmed source.",
            )
        )
        first = window.subtitle_state.get("asr_0001_s0001")
        self.assertIsNotNone(first)
        assert first is not None
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial(
                "asr_0001_s0002",
                "Current live source keeps growing",
                "Current live source keeps growing",
            )
        )
        window._flush_realtime_render()

        window._handle_translation_update(
            TranslationUpdate(
                segment_id=first.segment_id,
                source_version=first.version,
                source_text=first.source_text,
                translated_text="第一句译文。",
                source_language="en",
                target_language="zh-CN",
                provider="baidu-mt",
                is_final=True,
            )
        )

        self.assertEqual(
            window.overlay.source_label.text(),
            "Current live source keeps growing",
        )
        self.assertIn("第一句译文。", window.overlay.translation_label.text())

    def test_overlay_keeps_last_two_translations_when_current_source_is_untranslated(
        self,
    ) -> None:
        window = MainWindow(AppConfig())
        window._handle_realtime_subtitle_event(
            SubtitleEvent.final("asr_0001_s0001", "First sentence.", "First sentence.")
        )
        first = window.subtitle_state.get("asr_0001_s0001")
        self.assertIsNotNone(first)
        assert first is not None
        window._handle_translation_update(
            TranslationUpdate(
                segment_id=first.segment_id,
                source_version=first.version,
                source_text=first.source_text,
                translated_text="ZH first sentence.",
                source_language="en",
                target_language="zh-CN",
                provider="baidu-mt",
                is_final=True,
            )
        )
        window._handle_realtime_subtitle_event(
            SubtitleEvent.final("asr_0001_s0002", "Second sentence.", "Second sentence.")
        )
        second = window.subtitle_state.get("asr_0001_s0002")
        self.assertIsNotNone(second)
        assert second is not None
        window._handle_translation_update(
            TranslationUpdate(
                segment_id=second.segment_id,
                source_version=second.version,
                source_text=second.source_text,
                translated_text="ZH second sentence.",
                source_language="en",
                target_language="zh-CN",
                provider="baidu-mt",
                is_final=True,
            )
        )

        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial("asr_0001_s0003", "Third sentence", "Third sentence")
        )
        window._flush_realtime_render()

        visible_translations = [
            label.text()
            for label in window.overlay._sentence_labels
            if not label.isHidden()
        ]
        self.assertEqual(
            visible_translations,
            ["ZH first sentence.", "ZH second sentence."],
        )
        self.assertTrue(
            all(
                bool(label.property("captionCompleted"))
                for label in window.overlay._sentence_labels
                if not label.isHidden()
            )
        )
        self.assertEqual(window.overlay.source_label.text(), "Third sentence")

    def test_partial_history_updates_the_existing_item(self) -> None:
        window = MainWindow(AppConfig())
        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial("asr_0001", "first words", "first words")
        )
        window._flush_realtime_render()
        item = window.history_list.item(0)

        window._handle_realtime_subtitle_event(
            SubtitleEvent.partial(
                "asr_0001",
                "first words continue growing",
                "first words continue growing",
            )
        )
        window._flush_realtime_render()

        self.assertIs(window.history_list.item(0), item)
        self.assertEqual(window.history_list.count(), 1)
        self.assertIn("continue growing", item.text())

    def test_history_item_contains_only_english_and_chinese(self) -> None:
        window = MainWindow(AppConfig())
        event = SubtitleEvent.final(
            "asr_0001_s0001",
            "The source sentence.",
            "对应的中文翻译。",
        )

        segment = window.subtitle_state.apply(event)
        window._render_history_segment(segment)

        self.assertEqual(
            window.history_list.item(0).text(),
            "The source sentence.\n对应的中文翻译。",
        )
        self.assertNotIn("确认", window.history_list.item(0).text())


if __name__ == "__main__":
    unittest.main()
