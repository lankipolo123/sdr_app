import contextlib

from PySide6.QtWidgets import QWidget, QFrame, QHBoxLayout, QLabel, QCheckBox, QSizePolicy
from PySide6.QtCore import Qt, QTimer, Signal

from .power_button import PowerButton
from .level_slider import LevelSlider
from styles.theme_colors import (
    TEXT_MUTED, STATUS_OK, STATUS_ERROR, ACCENT_BLUE, BORDER_SUBTLE, TEXT_DARK,
    CONTENT_BG, checkbox_style,
)
from state.level_map import LEVEL_TO_HEX, HEX_TO_LEVEL, LEVEL_LABELS
from services.protocol import constants as c
from utils.time_format import format_uptime

SLIDER_SEND_DEBOUNCE_MS = 250
UPTIME_TICK_MS = 1000

# Fixed column widths shared between ChannelRow and ChannelTableHeader so
# header labels line up with the actual row content below them - a real
# table, not cards pretending to be one.
COL_CHECKBOX_W = 22
COL_CHANNEL_W = 46
COL_STATUS_W = 90
COL_MODE_W = 150
COL_POWER_W = 90
COL_LEVEL_W = 130
COL_UPTIME_W = 90
ROW_SPACING = 10
ROW_MARGINS = (12, 0, 12, 0)


class _ClickableLabel(QLabel):
    """Plain QLabel with a click signal - used for the status text/dot so
    it can double as the per-channel kill-switch reset control (click a
    tripped row's status to reset just that one), same idiom the C
    rewrite's status line uses."""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


@contextlib.contextmanager
def _signal_lock(widget):
    widget.blockSignals(True)
    try:
        yield
    finally:
        widget.blockSignals(False)


class ChannelTableHeader(QFrame):
    """Column titles for the channel table below - widths mirror
    ChannelRow's exactly so everything lines up."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChannelTableHeader")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(28)
        self.setStyleSheet(
            f"#ChannelTableHeader {{ background: {CONTENT_BG}; "
            f"border-bottom: 2px solid {BORDER_SUBTLE}; }}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(*ROW_MARGINS)
        row.setSpacing(ROW_SPACING)

        def _col(text: str, width: int, align=Qt.AlignLeft):
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            lbl.setAlignment(align | Qt.AlignVCenter)
            lbl.setStyleSheet(
                f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 700; "
                f"letter-spacing: 0.5px; background: transparent;"
            )
            return lbl

        row.addWidget(_col("", COL_CHECKBOX_W))
        row.addWidget(_col("CH", COL_CHANNEL_W))
        row.addWidget(_col("STATUS", COL_STATUS_W))
        row.addWidget(_col("MODE", COL_MODE_W))
        row.addWidget(_col("POWER", COL_POWER_W))
        row.addWidget(_col("LEVEL", COL_LEVEL_W))
        row.addStretch(1)
        row.addWidget(_col("UPTIME", COL_UPTIME_W, align=Qt.AlignRight))


class ChannelRow(QFrame):
    """One channel per row, not one channel per card - a dense,
    mixing-console-style table so all 16 channels are visible on screen
    at once without scrolling. Same controller/state/safety wiring as
    the card this replaces, just laid out horizontally."""

    ROW_HEIGHT = 40

    def __init__(self, controller, state, safety, selection, row_index: int = 0, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.state = state
        self.safety = safety
        self.selection = selection
        self.address = state.data.address
        self._alt = row_index % 2 == 1
        self._pending_level = None
        self._send_debounce = QTimer(self)
        self._send_debounce.setSingleShot(True)
        self._send_debounce.timeout.connect(self._send_debounced_level)

        self.setObjectName("ChannelRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(self.ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(*ROW_MARGINS)
        row.setSpacing(ROW_SPACING)

        self.select_checkbox = QCheckBox()
        self.select_checkbox.setFixedWidth(COL_CHECKBOX_W)
        self.select_checkbox.setStyleSheet(checkbox_style())
        self.select_checkbox.setToolTip(f"Select {self.controller.display_name} for bulk actions")
        self.select_checkbox.toggled.connect(lambda: self.selection.toggle(self.address))
        self.selection.changed.connect(self._on_selection_changed)
        row.addWidget(self.select_checkbox)

        self.channel_label = QLabel(f"CH{state.display_number:02d}")
        self.channel_label.setFixedWidth(COL_CHANNEL_W)
        self.channel_label.setStyleSheet(f"color: {TEXT_DARK}; font-weight: 700; font-size: 12px;")
        row.addWidget(self.channel_label)

        status_box = QWidget()
        status_box.setFixedWidth(COL_STATUS_W)
        status_row = QHBoxLayout(status_box)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)
        self.status_dot = _ClickableLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_text = _ClickableLabel("STANDBY")
        self.status_dot.clicked.connect(self._on_status_clicked)
        self.status_text.clicked.connect(self._on_status_clicked)
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_text)
        status_row.addStretch(1)
        row.addWidget(status_box)

        # Fixed mode indicator - every channel is Pseudo Random Noise only
        # now (see the removed channel_card.py in git history for why: the
        # old Mode combo/Set button and the Continuous Wave password gate
        # it used to gate were both removed entirely).
        self.mode_label = QLabel(c.MODE_NAMES[c.MODE_WHITE_NOISE])
        self.mode_label.setFixedWidth(COL_MODE_W)
        row.addWidget(self.mode_label)

        self.toggle = PowerButton()
        self.toggle.setFixedWidth(COL_POWER_W)
        row.addWidget(self.toggle)

        self.slider = LevelSlider()
        self.slider.setFixedWidth(COL_LEVEL_W)
        row.addWidget(self.slider)

        row.addStretch(1)

        self.uptime_label = QLabel()
        self.uptime_label.setFixedWidth(COL_UPTIME_W)
        self.uptime_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.uptime_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        row.addWidget(self.uptime_label)

        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._refresh_uptime)
        self._uptime_timer.start(UPTIME_TICK_MS)
        self._refresh_uptime()

        self.toggle.toggled.connect(self._on_toggle)
        self.slider.valueChanged.connect(self._on_slider)
        self.safety.changed.connect(self._on_safety_changed)

        self._style_row()
        self._style_mode_label(is_on=False)
        self.slider.setEnabled(False)

        state.changed.connect(self._on_hardware_state_changed)
        self._on_hardware_state_changed()

        self.controller.busy_changed.connect(self._on_busy_changed)

    def _style_row(self, is_on: bool = False):
        if self.safety.is_tripped(self.address):
            edge_color = STATUS_ERROR
        else:
            edge_color = ACCENT_BLUE if is_on else "transparent"
        bg = CONTENT_BG if self._alt else "#FFFFFF"
        self.setStyleSheet(
            f"#ChannelRow {{ background: {bg}; border: none; "
            f"border-bottom: 1px solid {BORDER_SUBTLE}; border-left: 3px solid {edge_color}; }}"
        )

    def _style_mode_label(self, is_on: bool):
        text_color = ACCENT_BLUE if is_on else TEXT_MUTED
        self.mode_label.setStyleSheet(
            f"QLabel {{ background: transparent; color: {text_color}; "
            f"font-weight: 600; font-size: 10px; }}"
        )

    def _on_toggle(self, checked: bool):
        if checked and not self.safety.allow_power_on(self.address):
            with _signal_lock(self.toggle):
                self.toggle.setChecked(False)
            return
        if checked:
            self.controller.turn_output_on()
        else:
            self.controller.turn_output_off()
        self.slider.setEnabled(checked)
        self._style_mode_label(is_on=checked)
        self._style_row(is_on=checked)
        target_level = self.state.data.last_level if checked else 0
        with _signal_lock(self.slider):
            self.slider.setValue(target_level)
        self._update_status(target_level)

    def _on_slider(self, value: int):
        if value > 0:
            self.state.data.last_level = value
        should_be_checked = value > 0
        if self.toggle.isChecked() != should_be_checked:
            with _signal_lock(self.toggle):
                self.toggle.setChecked(should_be_checked)
            self.slider.setEnabled(should_be_checked)
            self._style_mode_label(is_on=should_be_checked)
            self._style_row(is_on=should_be_checked)
        self._update_status(value)
        self._pending_level = value
        self._send_debounce.start(SLIDER_SEND_DEBOUNCE_MS)

    def _send_debounced_level(self):
        if self._pending_level is not None:
            self._send_level(self._pending_level)
            self._pending_level = None

    def _send_level(self, level: int):
        if level > 0 and not self.safety.allow_power_on(self.address):
            with _signal_lock(self.slider):
                self.slider.setValue(0)
            with _signal_lock(self.toggle):
                self.toggle.setChecked(False)
            self.slider.setEnabled(False)
            self._style_mode_label(is_on=False)
            self._style_row(is_on=False)
            self._update_status(0)
            return
        code = LEVEL_TO_HEX[level]
        if code is None:
            self.controller.turn_output_off()
        elif self.state.data.output_on:
            self.controller.set_power(code)
        else:
            self.controller.resume_output(code)

    def _on_busy_changed(self, busy: bool):
        if busy:
            self.status_text.setText("SENDING...")
            self.status_text.setStyleSheet(f"color: {ACCENT_BLUE}; font-size: 11px; font-weight: 600;")
            self.status_dot.setStyleSheet(f"background: {ACCENT_BLUE}; border-radius: 4px;")
        else:
            self._update_status(self.slider.value())

    def _on_hardware_state_changed(self):
        d = self.state.data
        level = 0 if not d.output_on else HEX_TO_LEVEL.get(d.power_code, d.last_level)

        if self.toggle.isChecked() != d.output_on:
            with _signal_lock(self.toggle):
                self.toggle.setChecked(d.output_on)

        self.slider.setEnabled(d.output_on)
        self._style_mode_label(is_on=d.output_on)
        self._style_row(is_on=d.output_on)

        if self.slider.value() != level:
            with _signal_lock(self.slider):
                self.slider.setValue(level)

        if level > 0:
            d.last_level = level

        self._update_status(level)

    def _update_status(self, level: int):
        tripped = self.safety.is_tripped(self.address)
        is_on = level > 0
        if tripped:
            self.status_text.setText("TRIPPED")
            color = STATUS_ERROR
        else:
            self.status_text.setText(LEVEL_LABELS[level].upper() if is_on else "STANDBY")
            color = STATUS_OK if is_on else TEXT_MUTED
        self.status_text.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600;")
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        cursor = Qt.PointingHandCursor if tripped else Qt.ArrowCursor
        self.status_text.setCursor(cursor)
        self.status_dot.setCursor(cursor)
        self.status_text.setToolTip("Click to reset this channel's kill switch trip" if tripped else "")

    def _on_status_clicked(self):
        if self.safety.is_tripped(self.address):
            self.safety.reset_one(self.address)

    def _on_safety_changed(self):
        self._style_row(is_on=self.toggle.isChecked())
        self._update_status(self.slider.value())

    def _refresh_uptime(self):
        self.uptime_label.setText(f"Up {format_uptime(int(self.state.current_uptime_seconds()))}")

    def _on_selection_changed(self):
        is_selected = self.selection.is_selected(self.address)
        if self.select_checkbox.isChecked() != is_selected:
            with _signal_lock(self.select_checkbox):
                self.select_checkbox.setChecked(is_selected)
