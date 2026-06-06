from __future__ import annotations

from PySide6.QtWidgets import QApplication


def apply_app_theme(app: QApplication) -> None:
    app.setStyleSheet(
        """
        QWidget#AppRoot {
            background: #101216;
            color: #edf2f7;
        }

        QFrame#Panel {
            background: #171b22;
            border: 1px solid #252b35;
            border-radius: 8px;
        }

        QFrame#LiveCaption {
            background: #0f141a;
            border: 1px solid #263443;
            border-radius: 8px;
        }

        QFrame#BottomBar {
            background: #151921;
            border: 1px solid #242a35;
            border-radius: 8px;
        }

        QFrame#OverlayContainer {
            background: rgba(13, 17, 23, 224);
            border: 1px solid rgba(148, 163, 184, 92);
            border-radius: 8px;
        }

        QLabel#WindowTitle {
            color: #f8fafc;
            font-size: 26px;
            font-weight: 700;
        }

        QLabel#WindowSubtitle,
        QLabel#BottomMeta,
        QLabel#FieldLabel {
            color: #9aa7b6;
            font-size: 13px;
        }

        QLabel#SectionTitle {
            color: #d8dee8;
            font-size: 15px;
            font-weight: 700;
        }

        QLabel#StatusBadge {
            background: #243225;
            border: 1px solid #3a7d44;
            border-radius: 16px;
            color: #8ee39d;
            font-weight: 700;
        }

        QLabel#MetricPill {
            background: #1e2a36;
            border: 1px solid #34506a;
            border-radius: 17px;
            color: #9fd3ff;
            font-weight: 600;
        }

        QLabel#SourceCaption {
            color: #7f8b99;
            font-size: 13px;
            font-weight: 400;
        }

        QLabel#TranslatedCaption {
            color: #f8fafc;
            font-size: 25px;
            font-weight: 700;
            line-height: 1.35;
        }

        QLabel#CorrectionHint {
            color: #ffd166;
            font-size: 13px;
        }

        QLabel#OverlayTranslation {
            color: #f8fafc;
            font-weight: 700;
        }

        QLabel#OverlaySource {
            color: #8d99a8;
            font-weight: 400;
        }

        QLabel#OverlayHint {
            color: #9aa7b6;
            font-size: 12px;
            font-weight: 600;
        }

        QLabel#OverlayStateBadge {
            background: rgba(45, 212, 191, 44);
            border: 1px solid rgba(45, 212, 191, 140);
            border-radius: 12px;
            color: #99f6e4;
            font-size: 12px;
            font-weight: 700;
        }

        QLabel#OverlayStateBadge[captionState="final"] {
            background: rgba(59, 130, 246, 44);
            border-color: rgba(96, 165, 250, 150);
            color: #bfdbfe;
        }

        QLabel#OverlayStateBadge[captionState="updated"] {
            background: rgba(245, 158, 11, 48);
            border-color: rgba(245, 158, 11, 160);
            color: #fde68a;
        }

        QPushButton {
            border-radius: 8px;
            padding: 0 14px;
            font-weight: 700;
        }

        QPushButton#PrimaryButton {
            background: #2dd4bf;
            border: 1px solid #48ead8;
            color: #042f2e;
        }

        QPushButton#PrimaryButton:hover {
            background: #5eead4;
        }

        QPushButton#GhostButton,
        QPushButton#SegmentButton,
        QPushButton#OverlayCloseButton {
            background: #202631;
            border: 1px solid #323a48;
            color: #d8dee8;
        }

        QPushButton#GhostButton:hover,
        QPushButton#SegmentButton:hover,
        QPushButton#OverlayCloseButton:hover {
            background: #283140;
            border-color: #465568;
        }

        QPushButton#SegmentButton:checked {
            background: #334155;
            border-color: #8ab4f8;
            color: #ffffff;
        }

        QComboBox#Input {
            min-height: 36px;
            padding: 0 10px;
            background: #10151c;
            border: 1px solid #2b3542;
            border-radius: 8px;
            color: #e5e7eb;
        }

        QComboBox#Input::drop-down {
            border: 0;
            width: 28px;
        }

        QListWidget#HistoryList {
            background: #10151c;
            border: 1px solid #26313e;
            border-radius: 8px;
            color: #d8dee8;
            padding: 8px;
        }

        QListWidget#HistoryList::item {
            min-height: 58px;
            padding: 10px;
            border-radius: 6px;
        }

        QListWidget#HistoryList::item:selected {
            background: #233041;
            color: #ffffff;
        }

        QSlider#Slider::groove:horizontal {
            height: 6px;
            border-radius: 3px;
            background: #2b3542;
        }

        QSlider#Slider::handle:horizontal {
            width: 16px;
            height: 16px;
            margin: -6px 0;
            border-radius: 8px;
            background: #8ab4f8;
        }
        """
    )

