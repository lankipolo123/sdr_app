# Both palettes' exact RGB values pulled from sdr_c's own COLOR_APP_*
# constants (main.c) - g_light_mode there defaults false (dark), same
# as this app defaults to dark. A few tokens are NOT re-themed (NAVY,
# TEXT_LIGHT, STATUS_ERROR_LIGHT) - they're the frameless custom title
# bar's fixed dark chrome, which doesn't change with the toggle any
# more than a native OS title bar would.
NAVY = "#1F2937"
TEXT_LIGHT = "#E5E7EB"
STATUS_ERROR_LIGHT = "#F87171"
RX_ACCENT = "#10B981"
SIDEBAR_SELECTED_TEXT = "#1F2937"

_DARK = {
    "PAGE_BG": "#202124",          # COLOR_APP_PAGE_BG
    "SURFACE": "#2B2D31",          # COLOR_APP_PANEL_BG
    "FIELD_BG": "#17181A",         # COLOR_APP_FIELD_BG
    "CONTENT_BG": "#242629",
    "ACCENT_BLUE": "#3AA8DD",      # COLOR_APP_HEADER
    "ACCENT_BLUE_DARK": "#1A85B8", # COLOR_APP_ACCENT
    "BORDER_SUBTLE": "#3F4247",    # COLOR_APP_PANEL_BORDER
    "BORDER_SUBTLE_DARK": "#1A1B1D",
    "NEUTRAL_TRACK": "#4B4E54",
    "SLIDER_HANDLE": "#C4C7CC",
    "TEXT_DARK": "#E8E9EA",        # COLOR_APP_TEXT
    "TEXT_MUTED": "#9A9CA0",       # COLOR_APP_MUTED
    "STATUS_OK": "#3AB55E",        # COLOR_APP_CONNECTED
    "STATUS_OK_DARK": "#2E9450",
    "STATUS_ERROR": "#E05A5A",     # COLOR_APP_DISCONNECTED
    "STATUS_ERROR_DARK": "#C24747",
    "WARNING_BG": "#4A3510",
    "WARNING_BORDER": "#F59E0B",
    "WARNING_TEXT": "#F5C451",
}

_LIGHT = {
    "PAGE_BG": "#F2F3F5",
    "SURFACE": "#FFFFFF",
    "FIELD_BG": "#ECEDF0",
    "CONTENT_BG": "#F5F6F8",
    "ACCENT_BLUE": "#1478AA",
    "ACCENT_BLUE_DARK": "#0F6E9E",
    "BORDER_SUBTLE": "#DBDDE1",
    "BORDER_SUBTLE_DARK": "#CED0D4",
    "NEUTRAL_TRACK": "#CBD5E1",
    "SLIDER_HANDLE": "#FFFFFF",
    "TEXT_DARK": "#1C1E21",
    "TEXT_MUTED": "#6E7176",
    "STATUS_OK": "#2E9B4E",
    "STATUS_OK_DARK": "#247A3E",
    "STATUS_ERROR": "#C63C3C",
    "STATUS_ERROR_DARK": "#9E2F2F",
    "WARNING_BG": "#FEF3C7",
    "WARNING_BORDER": "#F59E0B",
    "WARNING_TEXT": "#92400E",
}

_light_mode = False


def _apply(values: dict):
    globals().update(values)


_apply(_DARK)


def is_light_mode() -> bool:
    return _light_mode


def set_light_mode(light: bool):
    """Flips the whole palette in place - direct port of sdr_c's
    on_theme_toggle_clicked() (main.c), which does the same thing to
    its own COLOR_APP_* globals then repaints everything. Every color
    NAME here (ACCENT_BLUE, TEXT_DARK, ...) is reassigned to the new
    theme's value; components that did `from styles.theme_colors
    import ACCENT_BLUE` captured the OLD string and won't see this -
    they need `from styles import theme_colors` +
    `theme_colors.ACCENT_BLUE` instead, read fresh each time a widget
    is (re)built. The caller is responsible for actually rebuilding
    the widget tree afterward; this function only updates the palette
    itself."""
    global _light_mode
    _light_mode = light
    _apply(_LIGHT if light else _DARK)


def _cached_icon_path(icon_file: str, color: str, cache_key: str) -> str:
    import os
    import tempfile
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from components.icon_utils import tint_pixmap
    from utils.app_paths import resource_path

    cache_path = os.path.join(tempfile.gettempdir(), f"sdr_controller_{cache_key}.png")
    # Cache key must fold in the color - the same icon tinted a
    # different shade for light vs dark mode is a different file, not
    # a cache hit on the old one.
    if not os.path.exists(cache_path):
        source_path = resource_path("assets", "icons", "pages", icon_file)
        pixmap = QPixmap(source_path).scaled(12, 12, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pixmap = tint_pixmap(pixmap, color)
        pixmap.save(cache_path, "PNG")
    return cache_path.replace(os.sep, "/")


def checkbox_style() -> str:
    check_path = _cached_icon_path("check.png", "#FFFFFF", "checkbox_check")
    return f"""
QCheckBox {{ color: {TEXT_DARK}; background: transparent; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 2px solid {BORDER_SUBTLE}; background: {FIELD_BG};
}}
QCheckBox::indicator:hover {{
    border-color: {ACCENT_BLUE};
}}
QCheckBox::indicator:checked {{
    border: 2px solid {ACCENT_BLUE}; background: {ACCENT_BLUE};
    image: url({check_path});
}}
"""


def build_global_qss() -> str:
    arrow_path = _cached_icon_path("chevron-down.png", ACCENT_BLUE, f"dropdown_arrow_{ACCENT_BLUE.lstrip('#')}")
    spin_up_path = _cached_icon_path("chevron-up.png", ACCENT_BLUE, f"spin_up_arrow_{ACCENT_BLUE.lstrip('#')}")
    spin_down_path = _cached_icon_path("chevron-down.png", ACCENT_BLUE, f"spin_down_arrow_{ACCENT_BLUE.lstrip('#')}")
    return f"""
QChartView {{
    background: {SURFACE};
    border: 2px solid {BORDER_SUBTLE};
    border-radius: 8px;
}}
QPushButton {{
    background: {SURFACE};
    color: {TEXT_DARK};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 5px;
    padding: 4px 10px;
}}
QPushButton:hover {{
    border-color: {ACCENT_BLUE};
}}
QPushButton:pressed {{
    background: {CONTENT_BG};
}}
QPushButton#PrimaryButton {{
    background: {ACCENT_BLUE};
    color: #FFFFFF;
    border: none;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background: {ACCENT_BLUE_DARK};
}}
QPushButton#PrimaryButton:pressed {{
    background: {ACCENT_BLUE_DARK};
}}
QComboBox, QLineEdit, QSpinBox {{
    background: {FIELD_BG};
    color: {TEXT_DARK};
    border: 1px solid {BORDER_SUBTLE};
    border-radius: 5px;
    padding: 2px 6px;
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
    border-color: {ACCENT_BLUE};
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    color: {TEXT_DARK};
    border: 1px solid {BORDER_SUBTLE};
    outline: 0;
    selection-background-color: {ACCENT_BLUE};
    selection-color: #FFFFFF;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid {BORDER_SUBTLE};
    background: {NAVY};
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}}
QComboBox::down-arrow {{
    image: url({arrow_path});
    width: 12px;
    height: 12px;
    margin-right: 5px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    width: 18px;
    background: {NAVY};
    border-left: 1px solid {BORDER_SUBTLE};
}}
QSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: 4px;
    border-bottom: 1px solid {BORDER_SUBTLE_DARK};
}}
QSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: 4px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: {ACCENT_BLUE_DARK};
}}
QSpinBox::up-arrow {{
    image: url({spin_up_path});
    width: 9px;
    height: 9px;
}}
QSpinBox::down-arrow {{
    image: url({spin_down_path});
    width: 9px;
    height: 9px;
}}
QLineEdit:read-only {{
    background: {CONTENT_BG};
    color: {TEXT_MUTED};
}}
"""


def app_palette():
    from PySide6.QtGui import QPalette, QColor

    p = QPalette()
    p.setColor(QPalette.Window, QColor(PAGE_BG))
    p.setColor(QPalette.WindowText, QColor(TEXT_DARK))
    p.setColor(QPalette.Base, QColor(FIELD_BG))
    p.setColor(QPalette.AlternateBase, QColor(CONTENT_BG))
    p.setColor(QPalette.ToolTipBase, QColor(SURFACE))
    p.setColor(QPalette.ToolTipText, QColor(TEXT_DARK))
    p.setColor(QPalette.Text, QColor(TEXT_DARK))
    p.setColor(QPalette.Button, QColor(SURFACE))
    p.setColor(QPalette.ButtonText, QColor(TEXT_DARK))
    p.setColor(QPalette.BrightText, QColor(STATUS_ERROR))
    p.setColor(QPalette.Link, QColor(ACCENT_BLUE))
    p.setColor(QPalette.Highlight, QColor(ACCENT_BLUE))
    p.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(TEXT_MUTED))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TEXT_MUTED))
    return p
