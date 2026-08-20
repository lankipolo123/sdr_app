import contextlib

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSizePolicy
from PySide6.QtCore import Qt, QTimer

from .card import Card
from .power_button import PowerButton
from .level_slider import LevelSlider
from styles.theme_colors import TEXT_MUTED, STATUS_OK, ACCENT_BLUE, BORDER_SUBTLE, NAVY, TEXT_DARK
from state.level_map import LEVEL_TO_HEX, HEX_TO_LEVEL, LEVEL_LABELS, LEVEL_LABELS_FULL
from services.protocol import constants as c

SLIDER_SEND_DEBOUNCE_MS = 250


@contextlib.contextmanager
def _signal_lock(widget):
    widget.blockSignals(True)
    try:
        yield
    finally:
        widget.blockSignals(False)


class ChannelCard(Card):

    MIN_WIDTH = 200

    def __init__(self, controller, state, parent=None):
        super().__init__(f"CH{state.display_number:02d}", icon="fa5s.broadcast-tower")
        self.setMinimumWidth(self.MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.layout().setContentsMargins(8, 6, 8, 6)
        self.body_layout.setSpacing(4)
        self.controller = controller
        self.state = state
        self._pending_level = None
        self._send_debounce = QTimer(self)
        self._send_debounce.setSingleShot(True)
        self._send_debounce.timeout.connect(self._send_debounced_level)

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_text = QLabel("STANDBY")

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

        self.toggle.toggled.connect(self._on_toggle)
        self.slider.valueChanged.connect(self._on_slider)

        self._style_border()
        self.slider.setEnabled(False)

        state.changed.connect(self._on_hardware_state_changed)
        self._on_hardware_state_changed()

        self.controller.busy_changed.connect(self._on_busy_changed)

    def _style_border(self):
        self.setStyleSheet(
            f"#Card {{ background: #FFFFFF; border: 1px solid {BORDER_SUBTLE}; border-radius: 10px; }}"
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
        if checked:
            self.controller.turn_output_on()
        else:
            self.controller.turn_output_off()
        self.slider.setEnabled(checked)
        self._style_mode_combo(is_on=checked)
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
        self._update_status(value)
        self._pending_level = value
        self._send_debounce.start(SLIDER_SEND_DEBOUNCE_MS)

    def _send_debounced_level(self):
        if self._pending_level is not None:
            self._send_level(self._pending_level)
            self._pending_level = None

    def _on_mode_set(self):
        self.controller.set_mode(self._mode_codes[self.mode_combo.currentIndex()])

    def _send_level(self, level: int):
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
        is_on = level > 0
        self.status_text.setText(LEVEL_LABELS[level].upper() if is_on else "STANDBY")
        color = STATUS_OK if is_on else TEXT_MUTED
        self.status_text.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")

        for i, lbl in enumerate(self.level_labels):
            active = i == level
            lbl.setStyleSheet(
                f"color: {ACCENT_BLUE if active else TEXT_MUTED}; "
                f"font-weight: {'700' if active else '400'}; font-size: 11px;"
            )
