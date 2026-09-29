from PySide6.QtCore import QObject, Signal

# Bulk Actions selection - click a card's checkbox to toggle it in/out,
# then the Bulk Actions bar applies to every selected channel at once.
# Direct port of the C rewrite's g_channel_selected[]/Bulk Actions bar.
# Addresses are 0-based throughout, matching ChannelStateData.address.


class SelectionManager(QObject):

    changed = Signal()

    def __init__(self):
        super().__init__()
        self.selected: set[int] = set()
        # Whether the Bulk Actions row-select combo is on "Custom" - not
        # sdr_c's own behavior (its cards' checkboxes are always visible,
        # by its own explicit design comment), a direct app-only request:
        # Bulk Actions defaults to applying to every channel with no
        # per-channel checkboxes cluttering the cards, and those
        # checkboxes only appear once the user actively switches to
        # Custom to hand-pick specific channels. See ChannelCard's own
        # checkbox visibility and BulkActionsBar's combo handling.
        self.custom_mode: bool = False

    def set_custom_mode(self, value: bool):
        if self.custom_mode == value:
            return
        self.custom_mode = value
        self.changed.emit()

    def toggle(self, address: int):
        # Hand-editing one checkbox always means Custom, even if the
        # resulting set happens to numerically match a preset (e.g.
        # unchecking then rechecking the same box while "Select All" is
        # active) - custom_mode is real state set at the point of each
        # action, not re-derived from comparing the set to presets every
        # time (that re-derivation is exactly what silently snapped an
        # explicit "Custom" pick straight back to "Select All" whenever
        # the selection still happened to equal every channel).
        if address in self.selected:
            self.selected.discard(address)
        else:
            self.selected.add(address)
        self.custom_mode = True
        self.changed.emit()

    def select_all(self, addresses):
        # The one path that represents picking a PRESET (a row, "Select
        # All", or the plain Select All button) - always leaves Custom.
        self.selected = set(addresses)
        self.custom_mode = False
        self.changed.emit()

    def clear(self):
        # Same reasoning as toggle() - clearing by hand is Custom too.
        # Only emits if something actually changed (either the selection
        # was non-empty, or this leaves Custom mode for the first time) -
        # a Clear click that changes nothing shouldn't ripple a signal.
        changed = bool(self.selected) or not self.custom_mode
        self.selected.clear()
        self.custom_mode = True
        if changed:
            self.changed.emit()

    def is_selected(self, address: int) -> bool:
        return address in self.selected
