import contextlib

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QCheckBox, QSizePolicy
from PySide6.QtCore import Qt, QTimer, Signal

from .card import Card
from .power_button import PowerButton
from .level_slider import LevelSlider
from .password_dialog import PasswordDialog
from styles.theme_colors import TEXT_MUTED, STATUS_OK, STATUS_ERROR, ACCENT_BLUE, BORDER_SUBTLE, NAVY, TEXT_DARK, checkbox_style
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

    MIN_WIDTH = 200

    def __init__(self, controller, state, cw_auth, safety, selection, parent=None):
        super().__init__(f"CH{state.display_number:02d}", icon="broadcast-tower.png")
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.layout().setContentsMargins(8, 6, 8, 6)
        self.body_layout.setSpacing(4)
        self.controller = controller
        self.state = state
        self.cw_auth = cw_auth
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

        self._mode_codes = list(c.MODE_NAMES.keys())
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(c.MODE_NAMES.values()))
        self.mode_combo.setToolTip(self.mode_combo.currentText())
        self.mode_combo.currentTextChanged.connect(self.mode_combo.setToolTip)
        self._style_mode_combo(is_on=False)
        self.mode_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.mode_set_btn = QPushButton("Set")
        self.mode_set_btn.setFixedHeight(24)
        self.mode_set_btn.setCursor(Qt.PointingHandCursor)
        self.mode_set_btn.setToolTip("Set modulation")
        self.mode_set_btn.setStyleSheet(
            f"QPushButton {{ background: {NAVY}; color: {ACCENT_BLUE}; border: 1px solid {NAVY}; "
            f"border-radius: 7px; padding: 2px 6px; font-weight: 600; font-size: 10px; }}"
            f"QPushButton:disabled {{ background: transparent; color: {TEXT_MUTED}; border: 1px solid {BORDER_SUBTLE}; }}"
        )
        self.mode_set_btn.clicked.connect(self._on_mode_set)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        mode_row.addWidget(self.mode_combo, 1)
        mode_row.addWidget(self.mode_set_btn)
        left_col.addLayout(mode_row)

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
            f"#Card {{ background: #FFFFFF; border: 1px solid {border_color}; border-radius: 10px; }}"
        )

    def _style_mode_combo(self, is_on: bool):
        text_color = ACCENT_BLUE if is_on else TEXT_MUTED
        self.mode_combo.setStyleSheet(
            f"QComboBox {{ background: #FFFFFF; color: {text_color}; border: 1px solid {BORDER_SUBTLE}; "
            f"border-radius: 7px; padding: 2px 6px; font-weight: 600; font-size: 10px; }}"
            f"QComboBox::drop-down {{ border: none; background: transparent; }}"
            f"QComboBox QAbstractItemView {{ background: #FFFFFF; color: {TEXT_DARK}; "
            f"border: 1px solid {BORDER_SUBTLE}; border-radius: 8px; outline: 0; "
            f"selection-background-color: #FFFFFF; selection-color: {ACCENT_BLUE}; }}"
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
        self._style_mode_combo(is_on=checked)
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
            self._style_mode_combo(is_on=should_be_checked)
            self._style_border(is_on=should_be_checked)
        self._update_status(value)
        self._pending_level = value
        self._send_debounce.start(SLIDER_SEND_DEBOUNCE_MS)

    def _send_debounced_level(self):
        if self._pending_level is not None:
            self._send_level(self._pending_level)
            self._pending_level = None

    def _on_mode_set(self):
        mode = self._mode_codes[self.mode_combo.currentIndex()]
        if mode == c.MODE_SINGLE and not self._unlock_cw():
            self._revert_mode_combo()
            return
        self.controller.set_mode(mode)

    def _revert_mode_combo(self):
        current_mode = self.state.data.mode if self.state.data.mode is not None else c.BLIND_DEFAULT_MODE
        index = self._mode_codes.index(current_mode)
        with _signal_lock(self.mode_combo):
            self.mode_combo.setCurrentIndex(index)

    def _unlock_cw(self) -> bool:
        """Continuous Wave is a fixed, undithered carrier - the one mode
        this app gates behind a password (see CwAuth). Shared across every
        card: unlocking once (or setting the password the first time)
        covers the rest of the session, so this doesn't re-prompt per
        channel or per click."""
        if self.cw_auth.authorized:
            return True

        if not self.cw_auth.is_set():
            password = PasswordDialog.set_new(
                self, "Set Continuous Wave Password",
                "Continuous Wave (CW) mode needs a password before it can "
                "be armed. Set one now - you won't be asked again this "
                "session.",
            )
            if not password:
                return False
            self.cw_auth.set_password(password)
            return True

        def _verify(password):
            ok = self.cw_auth.verify(password)
            return ok, None if ok else "Wrong password - CW was not armed."

        password = PasswordDialog.ask(
            self, "Continuous Wave Password",
            "Enter the Continuous Wave password to arm CW mode.",
            on_submit=_verify,
        )
        return password is not None

    def _send_level(self, level: int):
        if level > 0 and not self.safety.allow_power_on(self.address):
            with _signal_lock(self.slider):
                self.slider.setValue(0)
            with _signal_lock(self.toggle):
                self.toggle.setChecked(False)
            self.slider.setEnabled(False)
            self._style_mode_combo(is_on=False)
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
        self._style_mode_combo(is_on=d.output_on)
        self._style_border(is_on=d.output_on)

        if self.slider.value() != level:
            with _signal_lock(self.slider):
                self.slider.setValue(level)

        mode_index = self._mode_codes.index(d.mode if d.mode is not None else c.BLIND_DEFAULT_MODE)
        if self.mode_combo.currentIndex() != mode_index:
            with _signal_lock(self.mode_combo):
                self.mode_combo.setCurrentIndex(mode_index)

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
