from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal
import qtawesome as qta

from .card import Card
from .power_button import PowerButton
from .level_slider import LevelSlider
from styles.theme_colors import TEXT_MUTED, STATUS_OK, ACCENT_BLUE
from state.level_map import LEVEL_TO_HEX, HEX_TO_LEVEL, LEVEL_LABELS, LEVEL_LABELS_FULL


class ChannelCard(Card):
    """One hardware channel's controls: a Power button ('Activate' /
    'Power Off', labeled by the action it performs) + a 3-position
    Level slider (Min/Med/Max only - no Off position, that's the
    toggle's job), with plain text labels under the slider marking each
    position - not buttons, just labels, the active one highlighted.

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

    disconnect_requested = Signal(int)  # address

    WIDTH = 220  # exposed so the grid that lays these out can size columns to match

    def __init__(self, controller, state, parent=None):
        super().__init__(f"CH{state.display_number:02d}", icon="fa5s.broadcast-tower")
        self.setFixedWidth(self.WIDTH)
        self.controller = controller
        self.state = state

        disconnect_btn = QPushButton()
        disconnect_btn.setIcon(qta.icon("fa5s.unlink", color=TEXT_MUTED))
        disconnect_btn.setFixedSize(20, 20)
        disconnect_btn.setFlat(True)
        disconnect_btn.setCursor(Qt.PointingHandCursor)
        disconnect_btn.setToolTip(
            "Disconnect this channel - use this before swapping which "
            "module is physically wired to a shared port"
        )
        disconnect_btn.clicked.connect(
            lambda: self.disconnect_requested.emit(self.state.data.address)
        )
        self.header_layout.addWidget(disconnect_btn)

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
        self.level_labels = {}
        for level in (1, 2, 3):
            lbl = QLabel(LEVEL_LABELS[level])
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setToolTip(LEVEL_LABELS_FULL[level])
            labels_row.addWidget(lbl)
            self.level_labels[level] = lbl
        self.body_layout.addLayout(labels_row)

        self.toggle = PowerButton()
        self.body_layout.addWidget(self.toggle)

        self.toggle.toggled.connect(self._on_toggle)
        self.slider.valueChanged.connect(self._on_slider)

        state.changed.connect(self._on_hardware_state_changed)
        self._on_hardware_state_changed()  # initial sync from real state

    # --- user-driven changes -------------------------------------------------

    def _on_toggle(self, checked: bool):
        if checked:
            level = self.state.data.last_level
            self.slider.blockSignals(True)
            self.slider.setValue(level)
            self.slider.blockSignals(False)
            self._update_status(level, on=True)
            self._send_level(level)
        else:
            self._update_status(self.state.data.last_level, on=False)
            self.controller.turn_output_off()

    def _on_slider(self, value: int):
        # No Off position on the slider anymore - any drag means "on at
        # this level," so it always implies the toggle should be checked.
        self.state.data.last_level = value
        if not self.toggle.isChecked():
            self.toggle.blockSignals(True)
            self.toggle.setChecked(True)
            self.toggle.blockSignals(False)
        self._update_status(value, on=True)
        self._send_level(value)

    def _send_level(self, level: int):
        code = LEVEL_TO_HEX[level]
        if self.state.data.output_on:
            self.controller.set_power(code)
        else:
            # Was off - needs an explicit Output Switch ON, not just a
            # Signal Control power change (see ChannelController.resume_output).
            self.controller.resume_output(code)

    # --- online/offline (module physically swapped out, on a shared port) --

    def set_offline(self):
        """Connection released (manual disconnect, e.g. before swapping
        which module is wired to a shared port) - card stays visible with
        its last known values, but controls are disabled since there's no
        live connection to send anything over."""
        self.controller = None
        self.toggle.setEnabled(False)
        self.slider.setEnabled(False)
        self.status_text.setText("OFFLINE")
        self.status_text.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; font-weight: 600;")
        self.status_dot.setStyleSheet(f"background: {TEXT_MUTED}; border-radius: 4px;")

    def set_online(self, controller):
        """The same address answered again (module physically swapped back
        in) - re-enable controls. Display already resynced itself via
        state.changed, since the controller's handle_frame() ran before
        this is called."""
        self.controller = controller
        self.toggle.setEnabled(True)
        self.slider.setEnabled(True)

    # --- real hardware state changes (Status Query responses, etc.) --------

    def _on_hardware_state_changed(self):
        d = self.state.data
        on = d.output_on
        level = HEX_TO_LEVEL.get(d.power_code, d.last_level) if on else d.last_level

        if self.toggle.isChecked() != on:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(on)
            self.toggle.blockSignals(False)

        if self.slider.value() != level:
            self.slider.blockSignals(True)
            self.slider.setValue(level)
            self.slider.blockSignals(False)

        if on:
            d.last_level = level

        self._update_status(level, on)

    def _update_status(self, level: int, on: bool):
        self.status_text.setText(LEVEL_LABELS[level].upper() if on else "STANDBY")
        color = STATUS_OK if on else TEXT_MUTED
        self.status_text.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")
        self.status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")

        for lvl, lbl in self.level_labels.items():
            active = on and lvl == level
            lbl.setStyleSheet(
                f"color: {ACCENT_BLUE if active else TEXT_MUTED}; "
                f"font-weight: {'700' if active else '400'}; font-size: 11px;"
            )
