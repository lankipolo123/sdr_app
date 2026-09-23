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

    def toggle(self, address: int):
        if address in self.selected:
            self.selected.discard(address)
        else:
            self.selected.add(address)
        self.changed.emit()

    def select_all(self, addresses):
        self.selected = set(addresses)
        self.changed.emit()

    def clear(self):
        if not self.selected:
            return
        self.selected.clear()
        self.changed.emit()

    def is_selected(self, address: int) -> bool:
        return address in self.selected
