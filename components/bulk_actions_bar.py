from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
from PySide6.QtCore import Qt

from styles import theme_colors
from state.level_map import LEVEL_LABELS

def _btn_style() -> str:
    # A function, not a module-level string - theme_colors.BORDER_SUBTLE
    # would otherwise be frozen in at import time and go stale after a
    # theme toggle.
    return f"QPushButton {{ border: 1px solid {theme_colors.BORDER_SUBTLE}; border-radius: 5px; padding: 3px 8px; font-size: 11px; }}"


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
    """Direct port of the C rewrite's Bulk Actions panel: check a card's
    checkbox to select it (see ChannelCard/SelectionManager), then apply
    ON/OFF/level to every selected channel at once. A compact 2-column
    panel - ON/OFF and Clear/Select All stacked on the left, Off/Low/
    Med/High stacked on the right - same shape as the C rewrite's own
    Bulk Actions card, not a single wide row. Loops the same per-channel
    controller calls a single card already uses - no new subsystem
    needed, this is purely a convenience over the existing
    ChannelController API."""

    def __init__(self, app_controller, parent=None):
        super().__init__(parent)
        self.app = app_controller
        self.setObjectName("BulkActionsBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#BulkActionsBar {{ background: {theme_colors.SURFACE}; border: 2px solid {theme_colors.BORDER_SUBTLE}; border-radius: 10px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        self.title_label = QLabel("Bulk Actions")
        self.title_label.setStyleSheet(f"color: {theme_colors.TEXT_DARK}; font-weight: 700; font-size: 12px;")
        outer.addWidget(self.title_label)

        columns = QHBoxLayout()
        columns.setSpacing(10)

        left_col = QVBoxLayout()
        left_col.setSpacing(6)

        on_off_row = QHBoxLayout()
        on_off_row.setSpacing(6)
        on_btn = _colored_btn("ON", theme_colors.STATUS_OK)
        on_btn.clicked.connect(self._on_bulk_on)
        on_off_row.addWidget(on_btn)
        off_btn = _colored_btn("OFF", theme_colors.STATUS_ERROR)
        off_btn.clicked.connect(self._on_bulk_off)
        on_off_row.addWidget(off_btn)
        left_col.addLayout(on_off_row)

        select_row = QHBoxLayout()
        select_row.setSpacing(6)
        select_all_btn = QPushButton("Select All")
        select_all_btn.setCursor(Qt.PointingHandCursor)
        select_all_btn.setStyleSheet(_btn_style())
        select_all_btn.clicked.connect(self._on_select_all)
        select_row.addWidget(select_all_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet(_btn_style())
        clear_btn.clicked.connect(self.app.selection.clear)
        select_row.addWidget(clear_btn)
        left_col.addLayout(select_row)

        left_col.addStretch(1)
        columns.addLayout(left_col, 1)
        columns.addWidget(self._divider())

        right_col = QVBoxLayout()
        right_col.setSpacing(4)
        right_col.addWidget(QLabel("Level:"))
        for level in reversed((0, 1, 2, 3)):
            btn = QPushButton(LEVEL_LABELS[level])
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(_btn_style())
            btn.clicked.connect(lambda _checked=False, lvl=level: self._on_bulk_level(lvl))
            right_col.addWidget(btn)
        columns.addLayout(right_col)

        outer.addLayout(columns)
        outer.addStretch(1)

        self.app.selection.changed.connect(self._refresh_title)
        self._refresh_title()

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setStyleSheet(f"color: {theme_colors.BORDER_SUBTLE};")
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
