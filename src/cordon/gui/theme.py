"""Palette and stylesheets.

Two looks, like the upstream launcher: the default PDA-inspired dark theme (graphite with amber
accents, referencing the in-game PDA) and a calmer "classic" light theme.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette


@dataclass(frozen=True)
class Palette:
    name: str
    window: str
    base: str
    alt_base: str
    text: str
    dim_text: str
    accent: str
    accent_text: str
    border: str
    danger: str
    warning: str
    ok: str


PDA = Palette(
    name="pda",
    window="#12110f",
    base="#1a1815",
    alt_base="#221e1a",
    text="#ece1ce",
    dim_text="#a09282",
    accent="#ffab00",
    accent_text="#181307",
    border="#342d25",
    danger="#ef5350",
    warning="#ffca28",
    ok="#66bb6a",
)

CLASSIC = Palette(
    name="classic",
    window="#f4f5f8",
    base="#ffffff",
    alt_base="#eaedf1",
    text="#1f2328",
    dim_text="#656d76",
    accent="#0969da",
    accent_text="#ffffff",
    border="#d0d7de",
    danger="#cf222e",
    warning="#d4a72c",
    ok="#1a7f37",
)


def palettes() -> dict[str, Palette]:
    return {PDA.name: PDA, CLASSIC.name: CLASSIC}


def qpalette(theme: Palette) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(theme.window))
    palette.setColor(QPalette.WindowText, QColor(theme.text))
    palette.setColor(QPalette.Base, QColor(theme.base))
    palette.setColor(QPalette.AlternateBase, QColor(theme.alt_base))
    palette.setColor(QPalette.Text, QColor(theme.text))
    palette.setColor(QPalette.Button, QColor(theme.alt_base))
    palette.setColor(QPalette.ButtonText, QColor(theme.text))
    palette.setColor(QPalette.Highlight, QColor(theme.accent))
    palette.setColor(QPalette.HighlightedText, QColor(theme.accent_text))
    palette.setColor(QPalette.ToolTipBase, QColor(theme.base))
    palette.setColor(QPalette.ToolTipText, QColor(theme.text))
    palette.setColor(QPalette.PlaceholderText, QColor(theme.dim_text))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(theme.dim_text))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(theme.dim_text))
    for group in (QPalette.Inactive, QPalette.Active):
        palette.setColor(group, QPalette.Highlight, QColor(theme.accent))
        palette.setColor(group, QPalette.HighlightedText, QColor(theme.accent_text))
    palette.setColor(QPalette.Inactive, QPalette.WindowText, QColor(theme.text))
    return palette


def stylesheet(theme: Palette, *, compact: bool = False) -> str:
    """Full stylesheet; *compact* shrinks fonts and paddings for small screens (1024x768)."""
    font_size = 11 if compact else 12
    button_padding = "4px 8px" if compact else "5px 12px"
    tab_padding = "5px 10px" if compact else "6px 16px"
    item_padding = "4px 6px" if compact else "6px 8px"
    header_padding = "4px 6px" if compact else "6px 8px"

    return f"""
    QWidget {{
        background-color: {theme.window};
        color: {theme.text};
        font-size: {font_size}px;
        font-family: 'Symbols Nerd Font', 'JetBrains Mono', 'JetBrainsMono Nerd Font', 'FiraCode Nerd Font', 'Hack Nerd Font', 'DejaVu Sans Mono', system-ui, sans-serif;
    }}
    QMainWindow::separator {{
        background: {theme.border};
        width: 1px;
        height: 1px;
    }}
    QWidget#header {{
        background: {theme.alt_base};
        border-bottom: 2px solid {theme.accent};
    }}
    QToolBar {{
        background: {theme.alt_base};
        border-bottom: 1px solid {theme.border};
        spacing: 6px;
        padding: 4px 6px;
    }}
    QToolButton#menuButton::menu-indicator {{
        image: none;
    }}
    QToolButton, QPushButton {{
        background-color: {theme.base};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 4px;
        padding: {button_padding};
        font-weight: 500;
    }}
    QToolButton:hover, QPushButton:hover {{
        background-color: {theme.alt_base};
        border-color: {theme.accent};
        color: {theme.accent};
    }}
    QToolButton:pressed, QPushButton:pressed {{
        background-color: {theme.window};
    }}
    QToolButton:disabled, QPushButton:disabled {{
        background-color: {theme.window};
        color: {theme.dim_text};
        border-color: {theme.border};
    }}
    QPushButton#primary {{
        background-color: {theme.accent};
        color: {theme.accent_text};
        border: 1px solid {theme.accent};
        border-radius: 4px;
        font-weight: bold;
        padding: 6px 18px;
    }}
    QPushButton#primary:hover {{
        background-color: {theme.text};
        color: {theme.window};
        border-color: {theme.text};
    }}
    QPushButton#primary:disabled {{
        background-color: {theme.border};
        color: {theme.dim_text};
        border-color: {theme.border};
    }}

    QListWidget, QTableWidget, QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox {{
        background-color: {theme.base};
        color: {theme.text};
        border: 1px solid {theme.border};
        border-radius: 4px;
        selection-background-color: #382c16;
        selection-color: {theme.text};
    }}
    QLineEdit:focus, QComboBox:focus, QTableWidget:focus {{
        border-color: {theme.accent};
    }}

    QListWidget::item {{
        border-radius: 4px;
        margin: 2px 3px;
        padding: {item_padding};
    }}
    QListWidget::item:hover {{
        background-color: {theme.alt_base};
    }}
    QListWidget::item:selected, QListWidget::item:selected:!active {{
        background-color: #382c16;
        color: {theme.accent};
        border: 1px solid {theme.accent};
    }}

    QTableView {{
        gridline-color: {theme.border};
        alternate-background-color: {theme.alt_base};
        border: 1px solid {theme.border};
        border-radius: 4px;
        selection-background-color: #382c16;
        selection-color: {theme.text};
    }}
    QTableView::item {{
        padding: 4px 6px;
    }}
    QTableView::item:selected, QTableView::item:selected:!active {{
        background-color: #382c16;
        color: {theme.text};
    }}
    QTableCornerButton::section {{
        background: {theme.alt_base};
        border: 0;
    }}
    QHeaderView::section {{
        background-color: {theme.alt_base};
        color: {theme.accent};
        border: none;
        border-bottom: 1px solid {theme.border};
        border-right: 1px solid {theme.border};
        padding: {header_padding};
        font-weight: bold;
    }}

    QTabWidget::pane {{
        border: 1px solid {theme.border};
        border-radius: 4px;
        top: -1px;
    }}
    QTabBar::tab {{
        background-color: {theme.window};
        border: 1px solid {theme.border};
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
        padding: {tab_padding};
        color: {theme.dim_text};
        margin-right: 2px;
    }}
    QTabBar::tab:hover {{
        color: {theme.text};
        background-color: {theme.alt_base};
    }}
    QTabBar::tab:selected {{
        background-color: {theme.base};
        color: {theme.accent};
        border-bottom: 2px solid {theme.accent};
        font-weight: bold;
    }}

    QGroupBox {{
        border: 1px solid {theme.border};
        border-radius: 4px;
        margin-top: 12px;
        padding-top: 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        color: {theme.accent};
        font-weight: bold;
    }}

    QStatusBar {{
        background: {theme.alt_base};
        border-top: 1px solid {theme.border};
        color: {theme.dim_text};
    }}
    QSplitter::handle {{
        background: {theme.border};
    }}

    QScrollBar:vertical {{
        background: {theme.window};
        width: 8px;
        margin: 0px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {theme.border};
        min-height: 20px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {theme.accent};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        height: 0px;
        background: none;
    }}

    QScrollBar:horizontal {{
        background: {theme.window};
        height: 8px;
        margin: 0px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {theme.border};
        min-width: 20px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {theme.accent};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        width: 0px;
        background: none;
    }}

    QLabel#headline {{
        color: {theme.accent};
        font-weight: bold;
        font-size: {font_size + 2}px;
    }}
    QLabel#brand {{
        color: {theme.accent};
        font-weight: bold;
        font-size: {font_size + 3}px;
        letter-spacing: 1px;
    }}
    QLabel#dim {{
        color: {theme.dim_text};
    }}
    QLabel#error {{
        color: {theme.danger};
    }}
    QLabel#warning {{
        color: {theme.warning};
    }}
    QLabel#ok {{
        color: {theme.ok};
    }}

    QCheckBox::indicator, QRadioButton::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 3px;
        border: 1px solid {theme.border};
        background: {theme.base};
    }}
    QCheckBox::indicator:checked {{
        background: {theme.accent};
        border-color: {theme.accent};
    }}

    QMenu {{
        background-color: {theme.base};
        border: 1px solid {theme.border};
        border-radius: 4px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 5px 20px 5px 10px;
        border-radius: 3px;
    }}
    QMenu::item:selected {{
        background-color: {theme.accent};
        color: {theme.accent_text};
    }}
    QToolTip {{
        background-color: {theme.base};
        color: {theme.text};
        border: 1px solid {theme.accent};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    """


def monospace(pixels: int = 12, *, bold: bool = False) -> QFont:
    font = QFont("monospace")
    font.setStyleHint(QFont.Monospace)
    font.setFamilies([
        "Symbols Nerd Font",
        "JetBrainsMono Nerd Font",
        "FiraCode Nerd Font",
        "Hack Nerd Font",
        "DejaVu Sans Mono",
        "monospace",
    ])
    font.setPixelSize(pixels)
    font.setBold(bold)
    return font


LEVEL_COLORS = {
    "error": PDA.danger,
    "warning": PDA.warning,
    "ok": PDA.ok,
    "info": PDA.dim_text,
}


def level_color(theme: Palette, level: str) -> str:
    return {
        "error": theme.danger,
        "warning": theme.warning,
        "ok": theme.ok,
        "info": theme.dim_text,
    }.get(level, theme.text)
