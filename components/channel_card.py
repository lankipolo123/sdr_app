import contextlib

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QLabel, QCheckBox, QSizePolicy
from PySide6.QtCore import Qt, QTimer, Signal

from .card import Card
from .power_button import PowerButton
from .level_slider import LevelSlider
from styles.theme_colors import TEXT_MUTED, STATUS_OK, STATUS_ERROR, ACCENT_BLUE, BORDER_SUBTLE, TEXT_DARK, SURFACE, checkbox_style
from state.level_map import LEVEL_TO_HEX, HEX_TO_LEVEL, LEVEL_LABELS, LEVEL_LABELS_FULL
from services.protocol import constants as c
from utils.time_format import format_uptime

SLIDER_SEND_DEBOUNCE_MS = 250
UPTIME_TICK_MS = 1000


class _ClickableLabel(QLabel):
    """Plain QLabel with a click signal - used for the status text/dot so
    it can double as the per-channel kill-switch reset control (click a
    tripped card's status to reset just that one), same idiom the C
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


class ChannelCard(Card):

    MIN_WIDTH = 180
    MAX_WIDTH = 240

    def __init__(self, controller, state, safety, selection, parent=None):
        super().__init__(f"CH{state.display_number:02d}", icon="broadcast-tower.png")
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setMaximumWidth(self.MAX_WIDTH)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.layout().setContentsMargins(6, 5, 6, 5)
        self.body_layout.setSpacing(3)
        self.controller = controller
        self.state = state
        self.safety = safety
        self.selection = selection
        self.address = state.data.address
        self._pending_level = None
        self._send_debounce = QTimer(self)
        self._send_debounce.setSingleShot(True)
        self._send_debounce.timeout.connect(self._send_debounced_level)

        # Bulk Actions selection - inserted at the front of the card's
        # own header row (title/icon), which Card already built.
        self.select_checkbox = QCheckBox()
        self.select_checkbox.setStyleSheet(checkbox_style())
        self.select_checkbox.setToolTip(f"Select {self.controller.display_name} for bulk actions")
        self.select_checkbox.toggled.connect(lambda: self.selection.toggle(self.address))
        self.header_layout.insertWidget(0, self.select_checkbox)
        self.selection.changed.connect(self._on_selection_changed)

        self.status_dot = _ClickableLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_text = _ClickableLabel("STANDBY")
        self.status_dot.clicked.connect(self._on_status_clicked)
        self.status_text.clicked.connect(self._on_status_clicked)

        main_row = QHBoxLayout()
        main_row.setSpacing(6)

        left_col = QVBoxLayout()
        left_col.setSpacing(4)

        # Fixed mode indicator - every channel is Pseudo Random Noise
        # only now (direct decision, removing the Mode combo + Set
        # button entirely, matching the C rewrite's own card). This
        # also retires the Continuous Wave password gate (CwAuth/
        # PasswordDialog) that used to live behind _on_mode_set() - CW
        # was the one mode it gated, and with mode selection gone
        # entirely there's nothing left for it to gate.
        self.mode_label = QLabel(c.MODE_NAMES[c.MODE_WHITE_NOISE])
        self.mode_label.setFixedHeight(20)
        self._style_mode_label(is_on=False)
        left_col.addWidget(self.mode_label)

        self.toggle = PowerButton()
        left_col.addWidget(self.toggle)

        status_row = QHBoxLayout()
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_text)
        status_row.addStretch()
        left_col.addLayout(status_row)
        left_col.addStretch()
        main_row.addLayout(left_col, 1)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(4)
        self.slider = LevelSlider()
        slider_row.addWidget(self.slider)

        labels_col = QVBoxLayout()
        labels_col.setContentsMargins(0, 0, 0, 0)
        labels_col.setSpacing(0)
        self.level_labels = [None] * 4
        for level in reversed(range(4)):
            lbl = QLabel(LEVEL_LABELS[level])
            lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            lbl.setToolTip(f"L{level} - {LEVEL_LABELS_FULL[level]}")
            labels_col.addWidget(lbl, 1)
            self.level_labels[level] = lbl
        slider_row.addLayout(labels_col)
        main_row.addLayout(slider_row)

        self.body_layout.addLayout(main_row)

        # Live-ticking "Up HH:MM:SS" odometer (see ChannelState's
        # current_uptime_seconds()) - an odometer fact about the
        # hardware, independent of connection status, same as the C
        # rewrite's per-channel uptime.
        self.uptime_label = QLabel()
        self.uptime_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        self.body_layout.addWidget(self.uptime_label)
        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._refresh_uptime)
        self._uptime_timer.start(UPTIME_TICK_MS)
        self._refresh_uptime()

        self.toggle.toggled.connect(self._on_toggle)
        self.slider.valueChanged.connect(self._on_slider)
        self.safety.changed.connect(self._on_safety_changed)

        self._style_border()
        self.slider.setEnabled(False)

        state.changed.connect(self._on_hardware_state_changed)
        self._on_hardware_state_changed()

        self.controller.busy_changed.connect(self._on_busy_changed)

    def _style_border(self, is_on: bool = False):
        if self.safety.is_tripped(self.address):
            border_color = STATUS_ERROR
        else:
            border_color = ACCENT_BLUE if is_on else BORDER_SUBTLE
        self.setStyleSheet(
            f"#Card {{ background: {SURFACE}; border: 1px solid {border_color}; border-radius: 10px; }}"
        )

    def _style_mode_label(self, is_on: bool):
        text_color = ACCENT_BLUE if is_on else TEXT_MUTED
        self.mode_label.setStyleSheet(
            f"QLabel {{ background: transparent; color: {text_color}; "
            f"padding: 2px 6px; font-weight: 600; font-size: 10px; }}"
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
        self._style_border(is_on=checked)
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
            self._style_border(is_on=should_be_checked)
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
            self._style_border(is_on=False)
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
            self.status_text.setStyleSheet(f"color: {ACCENT_BLUE}; font-size: 12px; font-weight: 600;")
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
        self._style_border(is_on=d.output_on)

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
        self.status_text.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        cursor = Qt.PointingHandCursor if tripped else Qt.ArrowCursor
        self.status_text.setCursor(cursor)
        self.status_dot.setCursor(cursor)
        self.status_text.setToolTip("Click to reset this channel's kill switch trip" if tripped else "")

        for i, lbl in enumerate(self.level_labels):
            active = i == level
            lbl.setStyleSheet(
                f"color: {ACCENT_BLUE if active else TEXT_MUTED}; "
                f"font-weight: {'700' if active else '400'}; font-size: 11px;"
            )

    def _on_status_clicked(self):
        if self.safety.is_tripped(self.address):
            self.safety.reset_one(self.address)

    def _on_safety_changed(self):
        self._style_border(is_on=self.toggle.isChecked())
        self._update_status(self.slider.value())

    def _refresh_uptime(self):
        self.uptime_label.setText(f"Up {format_uptime(int(self.state.current_uptime_seconds()))}")

    def _on_selection_changed(self):
        is_selected = self.selection.is_selected(self.address)
        if self.select_checkbox.isChecked() != is_selected:
            with _signal_lock(self.select_checkbox):
                self.select_checkbox.setChecked(is_selected)
