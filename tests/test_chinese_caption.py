import unittest

from app.core.chinese_caption import (
    ChineseCaptionComposer,
    normalize_chinese_caption_text,
)


class ChineseCaptionComposerTest(unittest.TestCase):
    def test_chinese_spacing_normalization_removes_provider_artifacts(self) -> None:
        self.assertEqual(
            normalize_chinese_caption_text(
                " 让 我们 从 财富 开始  ——  什么 是 财富 。 "
            ),
            "让我们从财富开始——什么是财富。",
        )
        self.assertEqual(
            normalize_chinese_caption_text("讨论 Transformer 模型 与 AI 推理。"),
            "讨论 Transformer 模型与 AI 推理。",
        )

    def test_unpunctuated_draft_stays_in_active_line(self) -> None:
        composer = ChineseCaptionComposer()

        frame = composer.accept_draft(
            segment_id="segment",
            source_version=1,
            translated_text="今天我们讨论实时翻译",
        )

        self.assertEqual(frame.stable_text, "")
        self.assertEqual(frame.active_text, "今天我们讨论实时翻译")

    def test_draft_keeps_full_preview_block_without_sentence_commit(self) -> None:
        composer = ChineseCaptionComposer()
        first = composer.accept_draft(
            segment_id="segment",
            source_version=1,
            translated_text="第一句话。第二句开始",
        )
        second = composer.accept_draft(
            segment_id="segment",
            source_version=2,
            translated_text="第一句话。第二句继续增长",
        )

        self.assertEqual(first.lines, ("第一句话。第二句开始",))
        self.assertEqual(second.stable_text, "")
        self.assertEqual(second.active_text, "第一句话。第二句继续增长")

    def test_moving_punctuation_does_not_commit_unstable_sentence(self) -> None:
        composer = ChineseCaptionComposer()
        composer.accept_draft(
            segment_id="segment",
            source_version=1,
            translated_text="今天我们讨论系统。然后测试性能",
        )
        frame = composer.accept_draft(
            segment_id="segment",
            source_version=2,
            translated_text="今天我们讨论系统然后测试。性能仍然稳定",
        )

        self.assertEqual(frame.stable_text, "")
        self.assertEqual(frame.active_text, "今天我们讨论系统然后测试。性能仍然稳定")

    def test_final_translation_is_kept_as_one_preview_block(self) -> None:
        composer = ChineseCaptionComposer()

        frame = composer.accept_final(
            segment_id="segment",
            source_version=3,
            translated_text="第一句话。第二句话！第三句话",
        )

        self.assertTrue(frame.is_final)
        self.assertEqual(frame.lines, ("第一句话。第二句话！第三句话",))

    def test_new_draft_keeps_previous_final_sentence_as_context(self) -> None:
        composer = ChineseCaptionComposer()
        composer.accept_final(
            segment_id="first",
            source_version=1,
            translated_text="上一句已经确认。",
        )
        frame = composer.accept_draft(
            segment_id="second",
            source_version=1,
            translated_text="当前句正在增长",
        )

        self.assertEqual(frame.lines, ("上一句已经确认。", "当前句正在增长"))

    def test_visible_window_uses_translation_blocks_not_chinese_sentences(self) -> None:
        composer = ChineseCaptionComposer(max_visible_lines=4)
        composer.accept_final(
            segment_id="first",
            source_version=1,
            translated_text="第一句。第二句。第三句。",
        )

        frame = composer.accept_draft(
            segment_id="second",
            source_version=1,
            translated_text="第四句正在更新",
        )

        self.assertEqual(
            frame.lines,
            ("第一句。第二句。第三句。", "第四句正在更新"),
        )
        self.assertEqual(frame.stable_text, "第一句。第二句。第三句。")

    def test_recent_sentence_buffer_is_bounded_for_long_sessions(self) -> None:
        composer = ChineseCaptionComposer(max_visible_lines=64)
        translated_text = "".join(f"第{index}句。" for index in range(80))

        frame = composer.accept_final(
            segment_id="long-session",
            source_version=1,
            translated_text=translated_text,
        )

        self.assertEqual(len(frame.lines), 1)
        self.assertEqual(frame.lines[0], translated_text)

    def test_stale_translation_does_not_replace_newer_draft(self) -> None:
        composer = ChineseCaptionComposer()
        composer.accept_draft(
            segment_id="segment",
            source_version=3,
            translated_text="较新的翻译草稿",
        )
        frame = composer.accept_draft(
            segment_id="segment",
            source_version=2,
            translated_text="过期翻译",
        )

        self.assertEqual(frame.active_text, "较新的翻译草稿")


if __name__ == "__main__":
    unittest.main()
