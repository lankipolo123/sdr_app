from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QFrame
from PySide6.QtCore import Qt

from styles.theme_colors import TEXT_DARK, BORDER_SUBTLE, NAVY, STATUS_OK, STATUS_ERROR, ACCENT_BLUE
from state.level_map import LEVEL_LABELS
from services.protocol import constants as c

_BTN_STYLE = f"QPushButton {{ border: 1px solid {BORDER_SUBTLE}; border-radius: 5px; padding: 3px 8px; font-size: 11px; }}"


def _colored_btn(text: str, bg: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ background: {bg}; border: 1px solid {bg}; border-radius: 5px; "
        f"padding: 3px 10px; font-size: 11px; font-weight: 600; color: white; }}"
        f"QPushButton:hover {{ background: {bg}; }}"
    )
    return btn


class BulkActionsBar(QFrame):
    """Direct port of the C rewrite's Bulk Actions bar: check a card's
    checkbox to select it (see ChannelCard/SelectionManager), then apply
    ON/OFF/Set-mode/Set-level to every selected channel at once. Loops
    the same per-channel controller calls a single card already uses -
    no new subsystem needed, this is purely a convenience over the
    existing ChannelController API."""

    def __init__(self, app_controller, parent=None):
        super().__init__(parent)
        self.app = app_controller
        self.setObjectName("BulkActionsBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#BulkActionsBar {{ background: #FFFFFF; border: 2px solid {BORDER_SUBTLE}; border-radius: 10px; }}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(6)

        self.title_label = QLabel("Bulk Actions")
        self.title_label.setStyleSheet(f"color: {TEXT_DARK}; font-weight: 700; font-size: 12px;")
        row.addWidget(self.title_label)

        select_all_btn = QPushButton("Select All")
        select_all_btn.setCursor(Qt.PointingHandCursor)
        select_all_btn.setStyleSheet(_BTN_STYLE)
        select_all_btn.clicked.connect(self._on_select_all)
        row.addWidget(select_all_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet(_BTN_STYLE)
        clear_btn.clicked.connect(self.app.selection.clear)
        row.addWidget(clear_btn)

        on_btn = _colored_btn("Bulk ON", STATUS_OK)
        on_btn.clicked.connect(self._on_bulk_on)
        row.addWidget(on_btn)

        off_btn = _colored_btn("Bulk OFF", STATUS_ERROR)
        off_btn.clicked.connect(self._on_bulk_off)
        row.addWidget(off_btn)

        row.addWidget(self._divider())

        row.addWidget(QLabel("Level:"))
        for level in (0, 1, 2, 3):
            btn = QPushButton(LEVEL_LABELS[level])
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(_BTN_STYLE)
            btn.clicked.connect(lambda _checked=False, lvl=level: self._on_bulk_level(lvl))
            row.addWidget(btn)

        row.addWidget(self._divider())

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(c.MODE_NAMES.values()))
        row.addWidget(self.mode_combo)

        set_mode_btn = QPushButton("Set Mode")
        set_mode_btn.setCursor(Qt.PointingHandCursor)
        set_mode_btn.setStyleSheet(
            f"QPushButton {{ background: {NAVY}; color: {ACCENT_BLUE}; border: 1px solid {NAVY}; "
            f"border-radius: 5px; padding: 3px 10px; font-size: 11px; font-weight: 600; }}"
        )
        set_mode_btn.clicked.connect(self._on_bulk_set_mode)
        row.addWidget(set_mode_btn)

        row.addStretch()

        self.app.selection.changed.connect(self._refresh_title)
        self._refresh_title()

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setStyleSheet(f"color: {BORDER_SUBTLE};")
        return line

    def _refresh_title(self):
        count = len(self.app.selection.selected)
        self.title_label.setText(f"Bulk Actions ({count} selected)" if count else "Bulk Actions")

    def _on_select_all(self):
        self.app.selection.select_all(range(len(self.app.channels.controllers)))

    def _on_bulk_on(self):
        # Tripped channels are skipped for ON, same as the C rewrite's
        # Bulk ON - OFF and Set are never gated by a trip.
        for address in self.app.selection.selected:
            if self.app.safety.allow_power_on(address):
                self.app.channels.get_controller(address).turn_output_on()

    def _on_bulk_off(self):
        for address in self.app.selection.selected:
            self.app.channels.get_controller(address).turn_output_off()

    def _on_bulk_level(self, level: int):
        from state.level_map import LEVEL_TO_HEX
        code = LEVEL_TO_HEX[level]
        for address in self.app.selection.selected:
            if code is not None and not self.app.safety.allow_power_on(address):
                continue
            controller = self.app.channels.get_controller(address)
            if code is None:
                controller.turn_output_off()
            elif controller.state.data.output_on:
                controller.set_power(code)
            else:
                controller.resume_output(code)

    def _on_bulk_set_mode(self):
        mode = list(c.MODE_NAMES.keys())[self.mode_combo.currentIndex()]
        for address in self.app.selection.selected:
            self.app.channels.get_controller(address).set_mode(mode)
