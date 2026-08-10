from PySide6.QtWidgets import QComboBox, QHBoxLayout, QVBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, QTimer, Signal

from .card import Card
from .power_button import PowerButton
from .level_slider import LevelSlider
from styles.theme_colors import TEXT_MUTED, STATUS_OK, ACCENT_BLUE, BORDER_SUBTLE, NAVY, TEXT_DARK
from state.level_map import LEVEL_TO_HEX, HEX_TO_LEVEL, LEVEL_LABELS, LEVEL_LABELS_FULL
from services.protocol import constants as c

# A drag across the slider fires valueChanged once per intermediate
# position it passes through (0 -> 1 -> 2 -> 3), not just the value it
# settles on - sending a real command per step stacked up to 3 separate
# Output-ON+Power pairs for one drag gesture, each taking a couple
# seconds to resolve, which looked like the level randomly climbing/
# dropping over several seconds after release. Debouncing the actual
# send (not the visual sync, which stays instant) means only the value
# the user actually stops on ever reaches the hardware.
SLIDER_SEND_DEBOUNCE_MS = 250


class ChannelCard(Card):
    """One hardware channel's controls, split left/right: the left column
    holds a Modulation dropdown (Pseudo Random Noise/Linear Sweep/
    Multi-tone/Spectral Line, see services/protocol/constants.MODE_NAMES)
    and explicit ON/OFF buttons (each sends exactly one command, same
    simplicity as the standalone Query diagnostic - see PowerButton); the
    right column is a vertical 4-position Level fader (L0-L3, bottom to
    top) with plain L0/L1/L2/L3 text labels beside it marking each
    position - not buttons, just labels, the active one highlighted.

    No Frequency/Bandwidth shown anywhere - the customer never sees that
    data, only Mode and Power. No Module Address shown either - the
    customer only ever sees the display number (CH01, CH02, ...), never
    the real protocol address.

    Every card has a live controller from launch and always sends
    blind - there's no discovery step and no online/offline state to
    wait on (see ChannelManager/ChannelController): a click just brute-
    force finds a port and fires the command, with retries and an
    optimistic apply if nothing answers.

    Locked until explicitly tapped: the slider and ON/OFF buttons start
    disabled, so nothing on this card can send until the user has
    clicked the card itself once first. Guards against an accidental
    drag/tap (e.g. a scroll gesture that catches a slider handle) firing
    a real command to hardware that's already unpredictable enough on a
    shared, collision-prone line - a genuine send should only ever
    follow a deliberate interaction with that specific card. Only one
    card is ever armed at a time - MainWindow listens for the `armed`
    signal and locks whichever card was previously armed back down, so
    arming CH02 doesn't leave CH01 sitting there still enabled too.
    Clicking anywhere outside every card (MainWindow's app-wide event
    filter) locks the armed one back down as well, so nothing stays
    unlocked once attention has moved off the cards entirely.

    Bidirectional reactive sync (toggle <-> slider <-> real hardware
    state), reusing the exact blockSignals() pattern from the old app's
    Device Control page so that syncing one widget from another's change
    never re-triggers a redundant hardware command - only a genuine user
    interaction sends a command.
    """

    MIN_WIDTH = 230  # the grid always uses 4 columns now (see MainWindow._reflow_grid) - this is a floor, not a fixed size

    armed = Signal()  # this card just became the armed one - MainWindow locks any other back down

    def __init__(self, controller, state, parent=None):
        super().__init__(f"CH{state.display_number:02d}", icon="fa5s.broadcast-tower")
        self.setMinimumWidth(self.MIN_WIDTH)
        # Stretches to fill its 1-of-4 share of the row instead of
        # staying a fixed pixel width - see MainWindow._reflow_grid's
        # column stretch factors, which is what actually divides the
        # available width evenly; this just allows the card to grow
        # into whatever share it's given instead of capping it.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # Tighter than Card's own default (14/10 outer, 7 body spacing) -
        # this card packs a dropdown, two buttons, and a fader into one
        # tile repeated 4-per-row, so it needs to run leaner than a
        # single-purpose card like the Controls panel does.
        self.layout().setContentsMargins(10, 8, 10, 8)
        self.body_layout.setSpacing(5)
        self.controller = controller
        self.state = state
        self._armed = False
        self._pending_level = None  # value to actually send once the debounce timer fires
        self._send_debounce = QTimer(self)
        self._send_debounce.setSingleShot(True)
        self._send_debounce.timeout.connect(self._send_debounced_level)

        status_row = QHBoxLayout()
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_text = QLabel("STANDBY")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_text)
        status_row.addStretch()
        self.arm_hint = QLabel("Tap twice to unlock")
        self.arm_hint.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-style: italic;")
        status_row.addWidget(self.arm_hint)
        self.body_layout.addLayout(status_row)

        main_row = QHBoxLayout()
        main_row.setSpacing(8)

        # Left column: Modulation dropdown on top, ON/OFF underneath.
        left_col = QVBoxLayout()
        left_col.setSpacing(5)

        # Order matches services/protocol/constants.MODE_NAMES exactly -
        # combo box index N always means self._mode_codes[N], not the
        # raw mode byte value directly (those happen to line up 0-3 too,
        # but building this list explicitly means it stays correct even
        # if MODE_NAMES's own codes/ordering ever changes).
        self._mode_codes = list(c.MODE_NAMES.keys())
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(c.MODE_NAMES.values()))
        # The longest name ("Pseudo Random Noise") still elides with an
        # ellipsis at this card's floor width - the tooltip always shows
        # the full current selection regardless of how narrow the card
        # actually ends up.
        self.mode_combo.setToolTip(self.mode_combo.currentText())
        self.mode_combo.currentTextChanged.connect(self.mode_combo.setToolTip)
        # Same navy/accent-blue pair and hover swap as the Clear Log
        # button (see pages/main_page.py) - rounded corners instead of
        # the plain white combo box the app-wide QSS gives every other
        # dropdown. Only styled while enabled (armed) - locked/disabled
        # falls back to a neutral, muted look so it's visually obvious
        # the card hasn't been tapped yet, same story the ON/OFF buttons
        # and slider already tell.
        self.mode_combo.setStyleSheet(
            f"QComboBox {{ background: {NAVY}; color: {ACCENT_BLUE}; border: 1px solid {NAVY}; "
            f"border-radius: 8px; padding: 3px 8px; font-weight: 600; font-size: 10px; }}"
            f"QComboBox:hover {{ background: {ACCENT_BLUE}; color: {NAVY}; }}"
            f"QComboBox:disabled {{ background: transparent; color: {TEXT_MUTED}; "
            f"border: 1px solid {BORDER_SUBTLE}; }}"
            f"QComboBox::drop-down {{ border: none; background: transparent; }}"
            f"QComboBox QAbstractItemView {{ background: #FFFFFF; color: {TEXT_DARK}; "
            f"border: 1px solid {BORDER_SUBTLE}; border-radius: 8px; outline: 0; "
            f"selection-background-color: {ACCENT_BLUE}; selection-color: #FFFFFF; }}"
        )
        left_col.addWidget(self.mode_combo)

        self.toggle = PowerButton()
        left_col.addWidget(self.toggle)
        left_col.addStretch()
        main_row.addLayout(left_col, 1)

        # Right column: the vertical fader, with L0-L3 labels beside it -
        # top to bottom Max/Med/Min/Off, matching the slider's own
        # bottom-is-minimum/top-is-maximum orientation. self.level_labels
        # stays indexed BY LEVEL (0-3), not by visual top-to-bottom
        # position, so _update_status's `enumerate(self.level_labels)`
        # keeps meaning "index i is level i" regardless of layout order.
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
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        # Locked by default - see _arm()/mousePressEvent below.
        self.slider.setEnabled(False)
        self.toggle.setEnabled(False)
        self.mode_combo.setEnabled(False)

        state.changed.connect(self._on_hardware_state_changed)
        self._on_hardware_state_changed()  # initial sync from real state

        self.controller.busy_changed.connect(self._on_busy_changed)

    # --- tap-to-arm lock -------------------------------------------------

    def mousePressEvent(self, event):
        # Only lands here for a press that isn't consumed by an
        # interactive child first - which, while locked, is every press
        # on this card (the slider/toggle are disabled and don't accept
        # mouse events), and once armed, anywhere that isn't the slider
        # or the ON/OFF buttons themselves.
        if not self._armed:
            self.arm()
        super().mousePressEvent(event)

    def arm(self):
        """Unlocks this card's slider/ON/OFF buttons and emits `armed` so
        MainWindow can lock any other card back down - only one card is
        ever armed at once. Normally triggered by tapping the card (see
        mousePressEvent); exposed as a public method too since a real
        click is the only other way to reach it, which tests need a
        direct way to trigger."""
        if self._armed:
            return
        self._armed = True
        self.slider.setEnabled(True)
        self.toggle.setEnabled(True)
        self.mode_combo.setEnabled(True)
        self.arm_hint.setVisible(False)
        self.setStyleSheet(
            f"#Card {{ background: #FFFFFF; border: 2px solid {ACCENT_BLUE}; border-radius: 10px; }}"
        )
        self.armed.emit()

    def disarm(self):
        """Locks this card back down - called on whichever card was
        previously armed when a different card gets tapped."""
        if not self._armed:
            return
        self._armed = False
        self.slider.setEnabled(False)
        self.toggle.setEnabled(False)
        self.mode_combo.setEnabled(False)
        self.arm_hint.setVisible(True)
        self.setStyleSheet(
            f"#Card {{ background: #FFFFFF; border: 2px solid {BORDER_SUBTLE}; border-radius: 10px; }}"
        )

    # --- user-driven changes -------------------------------------------------

    def _on_toggle(self, checked: bool):
        # Exactly one command, same simplicity as the standalone Query
        # diagnostic's ON/OFF - no bundled Signal Control/guessed
        # defaults riding along with it (see PowerButton).
        if checked:
            self.controller.turn_output_on()
        else:
            self.controller.turn_output_off()
        target_level = self.state.data.last_level if checked else 0
        self.slider.blockSignals(True)
        self.slider.setValue(target_level)
        self.slider.blockSignals(False)
        self._update_status(target_level)

    def _on_slider(self, value: int):
        if value > 0:
            self.state.data.last_level = value
        should_be_checked = value > 0
        if self.toggle.isChecked() != should_be_checked:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(should_be_checked)
            self.toggle.blockSignals(False)
        self._update_status(value)
        # Visual feedback above is instant, but the actual send is
        # debounced - a drag fires this once per intermediate position
        # it passes through, and sending a real command per step used
        # to stack up several redundant Output-ON+Power pairs for one
        # drag gesture (see SLIDER_SEND_DEBOUNCE_MS). Only the value
        # the user actually settles on, ~250ms after the last change,
        # gets sent.
        self._pending_level = value
        self._send_debounce.start(SLIDER_SEND_DEBOUNCE_MS)

    def _send_debounced_level(self):
        if self._pending_level is not None:
            self._send_level(self._pending_level)
            self._pending_level = None

    def _on_mode_changed(self, index: int):
        # A dropdown selection is a single discrete click, not a
        # continuous drag - no debounce needed the way the slider
        # needed one (see SLIDER_SEND_DEBOUNCE_MS).
        self.controller.set_mode(self._mode_codes[index])

    def _send_level(self, level: int):
        code = LEVEL_TO_HEX[level]
        if code is None:
            self.controller.turn_output_off()
        elif self.state.data.output_on:
            self.controller.set_power(code)
        else:
            # Was off - needs an explicit Output Switch ON, not just a
            # Signal Control power change (see ChannelController.resume_output).
            self.controller.resume_output(code)

    # --- in-flight feedback --------------------------------------------------

    def _on_busy_changed(self, busy: bool):
        # Fires while this card's controller has a command queued or
        # in-flight (see ChannelController.busy_changed) - shows plainly
        # that something is happening instead of leaving the card looking
        # idle for the ~1-2s a retry cycle can take. Not a popup/dialog -
        # reuses the card's own status line, same as the confirmed/
        # rejected/on/off states already do, so it doesn't block anything
        # and doesn't reintroduce the separate confirmation banner that
        # was removed earlier for not syncing well with real usage.
        if busy:
            self.status_text.setText("SENDING...")
            self.status_text.setStyleSheet(f"color: {ACCENT_BLUE}; font-size: 12px; font-weight: 600;")
            self.status_dot.setStyleSheet(f"background: {ACCENT_BLUE}; border-radius: 4px;")
        else:
            self._update_status(self.slider.value())

    # --- real hardware state changes (Status Query responses, etc.) --------

    def _on_hardware_state_changed(self):
        d = self.state.data
        level = 0 if not d.output_on else HEX_TO_LEVEL.get(d.power_code, d.last_level)

        if self.toggle.isChecked() != d.output_on:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(d.output_on)
            self.toggle.blockSignals(False)

        if self.slider.value() != level:
            self.slider.blockSignals(True)
            self.slider.setValue(level)
            self.slider.blockSignals(False)

        mode_index = self._mode_codes.index(d.mode if d.mode is not None else c.BLIND_DEFAULT_MODE)
        if self.mode_combo.currentIndex() != mode_index:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(mode_index)
            self.mode_combo.blockSignals(False)

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
