from PySide6.QtWidgets import QHBoxLayout, QLabel
from PySide6.QtCore import Qt

from .card import Card
from .power_button import PowerButton
from .level_slider import LevelSlider
from styles.theme_colors import TEXT_MUTED, STATUS_OK, ACCENT_BLUE
from state.level_map import LEVEL_TO_DB, DB_TO_LEVEL


class ChannelCard(Card):
    """One hardware channel's controls: a Power button ('Activate' /
    'Power Off', labeled by the action it performs) + a 4-position
    Level slider (L0-L3), with plain L0/L1/L2/L3 text labels under the
    slider marking each position - not buttons, just labels, the active
    one highlighted.

    No Mode/Frequency/Bandwidth shown anywhere - the customer never sees
    that data, only Power. No Module Address shown either - the customer
    only ever sees the display number (CH01, CH02, ...), never the real
    protocol address.

    Bidirectional reactive sync (toggle <-> slider <-> real hardware
    state), reusing the exact blockSignals() pattern from the old app's
    Device Control page so that syncing one widget from another's change
    never re-triggers a redundant hardware command - only a genuine user
    interaction sends a command.
    """

    def __init__(self, controller, state, parent=None):
        super().__init__(f"CH{state.display_number:02d}", icon="fa5s.broadcast-tower")
        self.setFixedWidth(220)
        self.controller = controller
        self.state = state

        status_row = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_text = QLabel("STANDBY")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_text)
        status_row.addStretch()
        self.body_layout.addLayout(status_row)

        self.slider = LevelSlider()
        self.body_layout.addWidget(self.slider)

        labels_row = QHBoxLayout()
        labels_row.setContentsMargins(0, 0, 0, 0)
        self.level_labels = []
        for level in range(4):
            lbl = QLabel(f"L{level}")
            lbl.setAlignment(Qt.AlignCenter)
            labels_row.addWidget(lbl)
            self.level_labels.append(lbl)
        self.body_layout.addLayout(labels_row)

        self.toggle = PowerButton()
        self.body_layout.addWidget(self.toggle)

        self.toggle.toggled.connect(self._on_toggle)
        self.slider.valueChanged.connect(self._on_slider)

        state.changed.connect(self._on_hardware_state_changed)
        self._on_hardware_state_changed()  # initial sync from real state

    # --- user-driven changes -------------------------------------------------

    def _on_toggle(self, checked: bool):
        target_level = self.state.data.last_level if checked else 0
        self.slider.blockSignals(True)
        self.slider.setValue(target_level)
        self.slider.blockSignals(False)
        self._update_status(target_level)
        self._send_level(target_level)

    def _on_slider(self, value: int):
        if value > 0:
            self.state.data.last_level = value
        should_be_checked = value > 0
        if self.toggle.isChecked() != should_be_checked:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(should_be_checked)
            self.toggle.blockSignals(False)
        self._update_status(value)
        self._send_level(value)

    def _send_level(self, level: int):
        db = LEVEL_TO_DB[level]
        if db is None:
            self.controller.turn_output_off()
        else:
            self.controller.set_power(db)

    # --- real hardware state changes (Status Query responses, etc.) --------

    def _on_hardware_state_changed(self):
        d = self.state.data
        level = 0 if not d.output_on else DB_TO_LEVEL.get(d.power_db, d.last_level)

        if self.toggle.isChecked() != d.output_on:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(d.output_on)
            self.toggle.blockSignals(False)

        if self.slider.value() != level:
            self.slider.blockSignals(True)
            self.slider.setValue(level)
            self.slider.blockSignals(False)

        if level > 0:
            d.last_level = level

        self._update_status(level)

    def _update_status(self, level: int):
        is_on = level > 0
        self.status_text.setText(f"L{level}" if is_on else "STANDBY")
        color = STATUS_OK if is_on else TEXT_MUTED
        self.status_text.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")

        for i, lbl in enumerate(self.level_labels):
            active = i == level
            lbl.setStyleSheet(
                f"color: {ACCENT_BLUE if active else TEXT_MUTED}; "
                f"font-weight: {'700' if active else '400'}; font-size: 11px;"
            )
