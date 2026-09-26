# Dark theme, exact RGB values pulled from sdr_c's own dark-mode
# palette (main.c's COLOR_APP_* constants, g_light_mode defaults false
# there too) - not an approximation, the real numbers the C rewrite
# ships with by default.
NAVY = "#1F2937"
PAGE_BG = "#202124"       # COLOR_APP_PAGE_BG - outer window/scroll background
SURFACE = "#2B2D31"       # COLOR_APP_PANEL_BG - card/dialog background, raised above PAGE_BG
FIELD_BG = "#17181A"      # COLOR_APP_FIELD_BG - inputs/combobox/checkbox background
CONTENT_BG = "#242629"    # between PAGE_BG and SURFACE - insets, read-only fields, heatmap wash
ACCENT_BLUE = "#3AA8DD"   # COLOR_APP_HEADER - section headers, icons, links
ACCENT_BLUE_DARK = "#1A85B8"  # COLOR_APP_ACCENT - hover/pressed accent
BORDER_SUBTLE = "#3F4247"     # COLOR_APP_PANEL_BORDER
BORDER_SUBTLE_DARK = "#1A1B1D"
NEUTRAL_TRACK = "#4B4E54"     # empty slider groove, visible against SURFACE
SLIDER_HANDLE = "#C4C7CC"     # sdr_c's silver_brush RGB(196,199,204)

TEXT_DARK = "#E8E9EA"     # COLOR_APP_TEXT - primary text (light, on dark backgrounds)
TEXT_MUTED = "#9A9CA0"    # COLOR_APP_MUTED
TEXT_LIGHT = "#E5E7EB"
SIDEBAR_SELECTED_TEXT = "#1F2937"

STATUS_OK = "#3AB55E"         # COLOR_APP_CONNECTED
STATUS_OK_DARK = "#2E9450"
STATUS_ERROR = "#E05A5A"      # COLOR_APP_DISCONNECTED
STATUS_ERROR_DARK = "#C24747"
STATUS_ERROR_LIGHT = "#F87171"
WARNING_BG = "#4A3510"
WARNING_BORDER = "#F59E0B"
WARNING_TEXT = "#F5C451"

TX_ACCENT = ACCENT_BLUE
RX_ACCENT = "#10B981"

DIALOG_BG = SURFACE

RADIO_BUTTON_STYLE = f"""
QRadioButton {{ color: {TEXT_DARK}; background: transparent; }}
QRadioButton::indicator {{
    width: 14px; height: 14px; border-radius: 7px;
    border: 2px solid {BORDER_SUBTLE}; background: transparent;
}}
QRadioButton::indicator:checked {{
    border: 2px solid {ACCENT_BLUE}; background: {ACCENT_BLUE};
}}
"""

def _cached_icon_path(icon_file: str, color: str, cache_key: str) -> str:
    import os
    import tempfile
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from components.icon_utils import tint_pixmap
    from utils.app_paths import resource_path

    cache_path = os.path.join(tempfile.gettempdir(), f"sdr_controller_{cache_key}.png")
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
    arrow_path = _cached_icon_path("chevron-down.png", ACCENT_BLUE, "dropdown_arrow")
    spin_up_path = _cached_icon_path("chevron-up.png", ACCENT_BLUE, "spin_up_arrow")
    spin_down_path = _cached_icon_path("chevron-down.png", ACCENT_BLUE, "spin_down_arrow")
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
