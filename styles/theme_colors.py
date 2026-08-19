NAVY = "#1F2937"
CONTENT_BG = "#F5F6F8"
ACCENT_BLUE = "#64AAFF"

TEXT_DARK = "#111827"
TEXT_MUTED = "#6B7280"
TEXT_LIGHT = "#E5E7EB"

STATUS_OK = "#087F23"
STATUS_ERROR = "#B00020"


def light_palette():
    from PySide6.QtGui import QPalette, QColor

    p = QPalette()
    p.setColor(QPalette.Window, QColor("#FFFFFF"))
    p.setColor(QPalette.WindowText, QColor(TEXT_DARK))
    p.setColor(QPalette.Base, QColor("#FFFFFF"))
    p.setColor(QPalette.AlternateBase, QColor(CONTENT_BG))
    p.setColor(QPalette.ToolTipBase, QColor("#FFFFFF"))
    p.setColor(QPalette.ToolTipText, QColor(TEXT_DARK))
    p.setColor(QPalette.Text, QColor(TEXT_DARK))
    p.setColor(QPalette.Button, QColor("#FFFFFF"))
    p.setColor(QPalette.ButtonText, QColor(TEXT_DARK))
    p.setColor(QPalette.BrightText, QColor(STATUS_ERROR))
    p.setColor(QPalette.Link, QColor(ACCENT_BLUE))
    p.setColor(QPalette.Highlight, QColor(ACCENT_BLUE))
    p.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(TEXT_MUTED))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TEXT_MUTED))
    return p
