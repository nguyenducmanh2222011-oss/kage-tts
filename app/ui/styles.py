"""
Theme stylesheets for KAGEVIETSUB TTS.
Style: Clean Minimal + Dark Cinematic + Desktop Utility (DaVinci Resolve / VS Code style)
Color Palette:
- Background:       #0D0F13
- Section/Panel:    #14171D
- Input/Dropdown:   #101319
- Border:           #272D36
- Text Primary:     #E8EDF3
- Secondary:        #8993A3
- Accent:           #08A8E8
- Success:          #18C77A
- Error:            #F05252
"""


def get_theme_stylesheet(is_dark: bool = True) -> str:
    return """
    /* Clean Minimal Dark Cinematic Utility Theme */
    QMainWindow, QWidget#centralWidget {
        background-color: #0D0F13;
        color: #E8EDF3;
        font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
        font-size: 12px;
    }

    /* Container */
    QWidget#mainContainer {
        background: transparent;
    }

    /* Section Panels */
    QFrame[panel="true"] {
        background-color: #14171D;
        border: 1px solid #272D36;
        border-radius: 6px;
    }

    QLabel {
        color: #E8EDF3;
        background: transparent;
    }

    QLabel[role="secTitle"] {
        font-weight: 700;
        font-size: 11px;
        color: #8993A3;
        letter-spacing: 0.6px;
    }

    /* Common Buttons */
    QPushButton {
        background-color: #1A1E26;
        color: #E8EDF3;
        border: 1px solid #272D36;
        border-radius: 5px;
        padding: 5px 12px;
        font-weight: 600;
        font-size: 12px;
    }
    QPushButton:hover {
        background-color: #222733;
        border-color: #08A8E8;
        color: #FFFFFF;
    }
    QPushButton:pressed {
        background-color: #14171D;
    }
    QPushButton:disabled {
        background-color: #101319;
        border-color: #1E232B;
        color: #4A5260;
    }

    /* The ONE primary CTA highlight button */
    QPushButton#startBtn {
        background-color: #08A8E8;
        color: #FFFFFF;
        border: 1px solid #0790C8;
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.5px;
        border-radius: 6px;
    }
    QPushButton#startBtn:hover {
        background-color: #18B5F5;
        border-color: #38C6FF;
    }
    QPushButton#startBtn:pressed {
        background-color: #067DAE;
    }
    QPushButton#startBtn:disabled {
        background-color: #18222E;
        border-color: #223040;
        color: #556B82;
    }

    QPushButton#cancelBtn {
        background-color: #3A181C;
        color: #F87171;
        border: 1px solid #5A2026;
        font-weight: 600;
        border-radius: 6px;
    }

    /* Inputs & Combos */
    QLineEdit, QComboBox, QSpinBox {
        background-color: #101319;
        border: 1px solid #272D36;
        border-radius: 5px;
        padding: 4px 8px;
        color: #E8EDF3;
        font-size: 12px;
        selection-background-color: #08A8E8;
    }
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
        border: 1px solid #08A8E8;
    }

    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 22px;
        border-left: 1px solid #272D36;
    }

    /* Restrain Dropdown Popup Height to ~8-10 items with clean scrollbar */
    QComboBox QAbstractItemView {
        background-color: #14171D;
        border: 1px solid #272D36;
        border-radius: 5px;
        color: #E8EDF3;
        selection-background-color: #1A2433;
        selection-color: #38C6FF;
        padding: 2px;
        outline: none;
        max-height: 220px;
    }

    /* Progress Bar */
    QProgressBar {
        border: none;
        border-radius: 3px;
        background-color: #101319;
        text-align: center;
        height: 6px;
        color: transparent;
    }
    QProgressBar::chunk {
        background-color: #08A8E8;
        border-radius: 3px;
    }

    /* DaVinci / VS Code style Table */
    QTableView {
        background-color: #0D0F13;
        alternate-background-color: #11141A;
        border: 1px solid #272D36;
        border-radius: 5px;
        gridline-color: transparent;
        color: #E8EDF3;
        font-size: 12px;
        selection-background-color: #182230;
        selection-color: #FFFFFF;
    }
    QTableView::item {
        padding: 4px 8px;
        border: none;
    }
    QTableView::item:hover {
        background-color: #161B24;
    }
    QHeaderView::section {
        background-color: #14171D;
        color: #8993A3;
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        padding: 6px 8px;
        border: none;
        border-bottom: 1px solid #272D36;
    }

    QScrollBar:vertical {
        background: #0D0F13;
        width: 6px;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: #272D36;
        border-radius: 3px;
        min-height: 20px;
    }
    QScrollBar::handle:vertical:hover {
        background: #3B4452;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
    }

    QStatusBar {
        background-color: #0D0F13;
        border-top: 1px solid #1E232B;
        color: #8993A3;
        font-size: 11px;
        padding: 2px 10px;
    }
    """
