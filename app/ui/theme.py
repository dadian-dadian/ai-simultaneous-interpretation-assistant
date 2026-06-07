from __future__ import annotations

from PySide6.QtWidgets import QApplication


def apply_app_theme(app: QApplication) -> None:
    app.setStyleSheet(
        """
        QWidget#AppRoot,
        QWidget#MainSurface {
            background: #f2f4f2;
            color: #1d2a27;
        }

        QFrame#TitleBar {
            background: #fcfdfc;
            border-bottom: 1px solid #dfe5e1;
        }

        QLabel#TitleBarMark {
            background: #e0eee9;
            border: 1px solid #c7ded6;
            border-radius: 6px;
            color: #2e7264;
            font-size: 11px;
            font-weight: 700;
        }

        QLabel#TitleBarTitle {
            color: #52615d;
            font-size: 12px;
            font-weight: 600;
        }

        QPushButton#WindowButton,
        QPushButton#WindowCloseButton {
            background: transparent;
            border: 0;
            border-radius: 6px;
            color: #64736f;
            font-size: 14px;
            font-weight: 500;
            padding: 0;
        }

        QPushButton#WindowButton:hover {
            background: #edf1ef;
            color: #1d2a27;
        }

        QPushButton#WindowCloseButton:hover {
            background: #f3e4e2;
            color: #963e36;
        }

        QFrame#Panel,
        QFrame#HistoryPanel {
            background: #fbfcfb;
            border: 1px solid #dce3df;
            border-radius: 12px;
        }

        QFrame#Divider {
            background: #e5eae7;
            border: 0;
        }

        QLabel#WindowTitle {
            color: #172420;
            font-size: 22px;
            font-weight: 700;
        }

        QLabel#WindowSubtitle {
            color: #7b8985;
            font-size: 12px;
        }

        QLabel#SectionTitle,
        QLabel#HistoryTitle {
            color: #22312d;
            font-size: 14px;
            font-weight: 700;
        }

        QLabel#HistoryTitle {
            font-size: 17px;
        }

        QLabel#HistorySubtitle,
        QLabel#FieldLabel {
            color: #84918d;
            font-size: 11px;
        }

        QLabel#FieldHint {
            color: #95a19d;
            font-size: 10px;
            padding-top: 1px;
        }

        QLabel#StatusBadge {
            background: #e3f0eb;
            border: 1px solid #c6ddd5;
            border-radius: 14px;
            color: #2e6f61;
            font-size: 12px;
            font-weight: 700;
        }

        QLabel#MetricPill,
        QLabel#HistoryCount {
            background: #edf2ef;
            border: 1px solid #dae4df;
            border-radius: 13px;
            color: #607b74;
            font-size: 10px;
            font-weight: 600;
            padding: 0 9px;
        }

        QLabel#HistoryCount {
            min-height: 22px;
        }

        QLabel#StatusNote {
            background: #f1f5f3;
            border: 1px solid #e1e8e4;
            border-radius: 7px;
            color: #73817d;
            font-size: 10px;
            padding: 7px 9px;
        }

        QPushButton {
            border-radius: 8px;
            padding: 0 11px;
            font-weight: 600;
        }

        QPushButton#PrimaryButton {
            background: #2f7466;
            border: 1px solid #2f7466;
            color: #ffffff;
        }

        QPushButton#PrimaryButton:hover {
            background: #28685b;
            border-color: #28685b;
        }

        QPushButton#PrimaryButton:pressed {
            background: #21584e;
        }

        QPushButton#GhostButton,
        QPushButton#SegmentButton {
            background: #f8faf9;
            border: 1px solid #d9e0dc;
            color: #475650;
        }

        QPushButton#GhostButton:hover,
        QPushButton#SegmentButton:hover {
            background: #f0f4f2;
            border-color: #c7d3ce;
        }

        QPushButton#GhostButton:checked,
        QPushButton#SegmentButton:checked {
            background: #e2efea;
            border-color: #82aa9f;
            color: #275e53;
        }

        QPushButton:disabled {
            background: #f0f2f1;
            border-color: #e2e6e4;
            color: #a8b1ae;
        }

        QComboBox#Input {
            min-height: 33px;
            padding: 0 10px;
            background: #ffffff;
            border: 1px solid #d9e0dc;
            border-radius: 8px;
            color: #34433e;
            selection-background-color: #dfece7;
        }

        QLabel#InputValue {
            min-height: 33px;
            padding: 0 10px;
            background: #f4f7f5;
            border: 1px solid #e0e6e3;
            border-radius: 8px;
            color: #52615d;
        }

        QComboBox#Input:hover,
        QComboBox#Input:focus {
            border-color: #86aa9f;
        }

        QComboBox#Input::drop-down {
            border: 0;
            width: 26px;
        }

        QComboBox QAbstractItemView {
            background: #ffffff;
            border: 1px solid #d9e0dc;
            color: #34433e;
            selection-background-color: #e3efeb;
            selection-color: #244f46;
            padding: 4px;
            outline: 0;
        }

        QListWidget#HistoryList {
            background: #f7f9f8;
            border: 1px solid #e3e8e5;
            border-radius: 9px;
            color: #84918d;
            padding: 5px;
            outline: 0;
        }

        QListWidget#HistoryList::item {
            background: transparent;
            border: 0;
            border-bottom: 1px solid #e7ece9;
            padding: 0;
        }

        QListWidget#HistoryList::item:hover {
            background: #f0f5f2;
        }

        QListWidget#HistoryList::item:selected {
            background: #e7f1ed;
            color: #244f46;
        }

        QWidget#HistoryEntry {
            background: transparent;
        }

        QWidget#HistoryEmpty {
            background: transparent;
        }

        QLabel#HistoryEmptyMark {
            background: #e4efeb;
            border: 1px solid #cbded7;
            border-radius: 20px;
            color: #397769;
            font-size: 17px;
            font-weight: 700;
        }

        QLabel#HistoryEmptyTitle {
            color: #52625d;
            font-size: 14px;
            font-weight: 600;
        }

        QLabel#HistoryEmptySubtitle {
            color: #95a19d;
            font-size: 11px;
        }

        QLabel#HistorySource {
            color: #82908c;
            font-size: 11px;
            font-weight: 400;
        }

        QLabel#HistoryTranslation {
            color: #25332f;
            font-size: 14px;
            font-weight: 600;
        }

        QScrollBar:vertical {
            background: transparent;
            width: 7px;
            margin: 3px 0;
        }

        QScrollBar::handle:vertical {
            background: #cbd4d0;
            min-height: 28px;
            border-radius: 3px;
        }

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {
            background: transparent;
            border: 0;
            height: 0;
        }

        QSlider#Slider::groove:horizontal {
            height: 4px;
            border-radius: 2px;
            background: #dce2df;
        }

        QSlider#Slider::sub-page:horizontal {
            border-radius: 2px;
            background: #76a99c;
        }

        QSlider#Slider::handle:horizontal {
            width: 14px;
            height: 14px;
            margin: -5px 0;
            border: 2px solid #347769;
            border-radius: 7px;
            background: #ffffff;
        }

        QFrame#OverlayContainer {
            background: qlineargradient(
                x1: 0, y1: 0, x2: 1, y2: 1,
                stop: 0 rgba(251, 252, 250, 250),
                stop: 1 rgba(242, 246, 248, 250)
            );
            border: 1px solid rgba(154, 168, 178, 150);
            border-radius: 14px;
        }

        QFrame#OverlaySourceBar {
            background: rgba(96, 119, 137, 10);
            border: 0;
            border-radius: 6px;
        }

        QScrollArea#OverlayTranslationScroll,
        QScrollArea#OverlaySourceScroll,
        QWidget#OverlayTranslationContent {
            background: transparent;
            border: 0;
        }

        QFrame#OverlayDivider {
            background: rgba(112, 128, 139, 46);
            border: 0;
        }

        QLabel#OverlayTranslation {
            color: #26343a;
            font-weight: 500;
        }

        QLabel#OverlayTranslation[captionCompleted="true"],
        QLabel#OverlayTranslationCompleted {
            color: #8b989d;
            font-weight: 400;
        }

        QLabel#OverlaySource {
            color: #647984;
            font-weight: 400;
        }

        QLabel#OverlaySourceLanguage {
            background: rgba(91, 119, 137, 13);
            border: 1px solid rgba(105, 130, 145, 42);
            border-radius: 5px;
            color: #768b96;
            font-size: 9px;
            font-weight: 700;
        }

        QPushButton#OverlayCloseButton {
            background: rgba(255, 255, 255, 160);
            border: 1px solid rgba(126, 144, 154, 48);
            border-radius: 8px;
            color: #7e8d94;
            font-size: 17px;
            font-weight: 400;
            padding: 0;
        }

        QPushButton#OverlayCloseButton:hover {
            background: rgba(229, 96, 91, 20);
            border-color: rgba(205, 97, 91, 65);
            color: #b85f59;
        }

        QPushButton#OverlayCloseButton:pressed {
            background: rgba(229, 96, 91, 34);
            color: #9f4d48;
        }

        QSizeGrip#OverlayResizeGrip {
            background: transparent;
            border-right: 2px solid rgba(111, 132, 143, 100);
            border-bottom: 2px solid rgba(111, 132, 143, 100);
        }
        """
    )
