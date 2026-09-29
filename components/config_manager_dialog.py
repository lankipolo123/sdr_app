from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QLineEdit, QMessageBox, QFrame, QInputDialog, QWidget,
)
from PySide6.QtCore import Qt

from styles import theme_colors
from state.level_map import LEVEL_LABELS
from utils.config_slots import (
    list_config_slots, load_config_slot, load_config_location, save_config_slot,
    delete_config_slot, rename_config_slot, MAX_CONFIG_SLOTS,
)

MAX_CHANNELS = 16


class ConfigManagerDialog(QDialog):
    """Custom Load/Save Config dialog: up to MAX_CONFIG_SLOTS saved
    configs listed on the left, and a live per-channel power-level
    preview on the right - the selected slot's own contents in Load
    mode (so you see what you're about to load before committing), the
    rack's CURRENT live state in Save mode (so you see what you're
    about to write). Not a sdr_c port - sdr_c's own Load/Save Config is
    a single-file native picker with no slots or preview at all; this
    is a genuinely new feature, direct request."""

    def __init__(self, parent, app_controller, mode: str):
        super().__init__(parent)
        assert mode in ("load", "save")
        self.app = app_controller
        self.mode = mode
        self.result_name: str | None = None

        self.setWindowTitle("Load Config" if mode == "load" else "Save Config")
        self.resize(600, 440)
        self.setStyleSheet(f"QDialog {{ background: {theme_colors.SURFACE}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        row = QHBoxLayout()
        row.setSpacing(18)

        # ---- Left: saved config slots ----
        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        left_header = QLabel("Load Config" if mode == "load" else "Save Config")
        left_header.setStyleSheet(f"color: {theme_colors.TEXT_DARK}; font-weight: 700; font-size: 13px;")
        left_col.addWidget(left_header)

        self.count_label = QLabel()
        self.count_label.setStyleSheet(f"color: {theme_colors.TEXT_MUTED}; font-size: 11px;")
        left_col.addWidget(self.count_label)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        left_col.addWidget(self.list_widget, 1)

        slot_actions_row = QHBoxLayout()
        slot_actions_row.setSpacing(6)

        self.rename_btn = QPushButton("Rename")
        self.rename_btn.setCursor(Qt.PointingHandCursor)
        self.rename_btn.setStyleSheet(
            f"QPushButton {{ color: {theme_colors.ACCENT_BLUE}; border: 1px solid {theme_colors.ACCENT_BLUE}; "
            f"border-radius: 5px; padding: 4px 10px; background: transparent; }}"
            f"QPushButton:hover {{ background: {theme_colors.ACCENT_BLUE}; color: white; }}"
            f"QPushButton:disabled {{ color: {theme_colors.TEXT_MUTED}; border-color: {theme_colors.BORDER_SUBTLE}; }}"
        )
        self.rename_btn.clicked.connect(self._on_rename_clicked)
        slot_actions_row.addWidget(self.rename_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setStyleSheet(
            f"QPushButton {{ color: {theme_colors.STATUS_ERROR}; border: 1px solid {theme_colors.STATUS_ERROR}; "
            f"border-radius: 5px; padding: 4px 10px; background: transparent; }}"
            f"QPushButton:hover {{ background: {theme_colors.STATUS_ERROR}; color: white; }}"
            f"QPushButton:disabled {{ color: {theme_colors.TEXT_MUTED}; border-color: {theme_colors.BORDER_SUBTLE}; }}"
        )
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        slot_actions_row.addWidget(self.delete_btn)

        left_col.addLayout(slot_actions_row)

        self.name_edit = None
        self.location_edit = None
        if mode == "save":
            name_label = QLabel("Name")
            name_label.setStyleSheet(f"color: {theme_colors.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
            left_col.addWidget(name_label)

            self.name_edit = QLineEdit()
            self.name_edit.setPlaceholderText("Config name")
            self.name_edit.textChanged.connect(self._refresh_buttons)
            left_col.addWidget(self.name_edit)

            # Direct request: a persistent caption, not just a
            # placeholder that disappears once you start typing - and
            # an optional tag describing where this config applies
            # (e.g. "Bay 1", "Rack A"), shown in the slot list instead
            # of channel-count/save-date, which weren't considered
            # useful detail.
            location_label = QLabel("Location")
            location_label.setStyleSheet(f"color: {theme_colors.TEXT_MUTED}; font-size: 11px; font-weight: 600;")
            left_col.addWidget(location_label)

            self.location_edit = QLineEdit()
            self.location_edit.setPlaceholderText("e.g. Bay 1 (optional)")
            left_col.addWidget(self.location_edit)

        row.addLayout(left_col, 1)

        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setStyleSheet(f"color: {theme_colors.BORDER_SUBTLE};")
        row.addWidget(divider)

        # ---- Right: per-channel power preview ----
        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        right_header = QLabel("Channel Power" if mode == "load" else "Current Channel Power")
        right_header.setStyleSheet(f"color: {theme_colors.TEXT_DARK}; font-weight: 700; font-size: 13px;")
        right_col.addWidget(right_header)

        self.empty_preview_label = QLabel(
            "No channels are on" if mode == "save" else "This config has no active channels"
        )
        self.empty_preview_label.setStyleSheet(f"color: {theme_colors.TEXT_MUTED}; font-size: 12px;")
        self.empty_preview_label.setVisible(False)
        right_col.addWidget(self.empty_preview_label)

        preview_grid = QGridLayout()
        preview_grid.setSpacing(4)
        self.channel_labels: list[QLabel] = []
        for address in range(MAX_CHANNELS):
            row_i, col_i = divmod(address, 2)
            lbl = QLabel()
            lbl.setStyleSheet(f"color: {theme_colors.ACCENT_BLUE}; font-size: 12px; font-weight: 700;")
            lbl.setVisible(False)
            preview_grid.addWidget(lbl, row_i, col_i)
            self.channel_labels.append(lbl)
        right_col.addLayout(preview_grid)
        right_col.addStretch(1)

        row.addLayout(right_col, 1)
        outer.addLayout(row, 1)

        # ---- Bottom buttons ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self.action_btn = QPushButton("Load" if mode == "load" else "Save")
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.setStyleSheet(
            f"QPushButton {{ background: {theme_colors.ACCENT_BLUE}; color: white; border: none; "
            f"border-radius: 5px; padding: 6px 18px; font-weight: 600; }}"
            f"QPushButton:disabled {{ background: {theme_colors.BORDER_SUBTLE}; color: {theme_colors.TEXT_MUTED}; }}"
        )
        self.action_btn.clicked.connect(self._on_action_clicked)
        btn_row.addWidget(self.action_btn)

        outer.addLayout(btn_row)

        self._reload_slot_list()
        if mode == "save":
            self._show_live_preview()
        self._refresh_buttons()

    def _reload_slot_list(self):
        self.list_widget.clear()
        for name in list_config_slots(self.app.config):
            # Item TEXT is deliberately left empty - the custom row
            # widget below (setItemWidget) draws the name itself, and a
            # non-empty item text painted underneath a widget that
            # doesn't fully opaque its background double-draws (a real
            # bug caught in testing: name showed twice, faint text
            # bleeding through under the bold label). The real name
            # lives in Qt.UserRole instead - every other method here
            # (selection/rename/delete/load/the save overwrite check)
            # reads it from there now, never from item.text().
            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            self.list_widget.addItem(item)
            row_widget = self._build_slot_row_widget(name)
            item.setSizeHint(row_widget.sizeHint())
            self.list_widget.setItemWidget(item, row_widget)
        self.count_label.setText(f"{self.list_widget.count()}/{MAX_CONFIG_SLOTS} saved")

    def _build_slot_row_widget(self, name: str) -> QWidget:
        # Direct request: the slot list showed only the bare save name -
        # "needs more details showing", later refined to specifically
        # want a location tag ("Bay 1", "Rack A" - set via
        # location_edit in Save mode) rather than channel-count/save-
        # date, which weren't considered useful. Location is the
        # primary detail shown; channel count is the fallback for a
        # slot saved without one, so a row is never blank.
        location = load_config_location(self.app.config, name)
        if location:
            detail_text = location
        else:
            entries = load_config_slot(self.app.config, name)
            channel_count = len(entries)
            plural = "" if channel_count == 1 else "s"
            detail_text = f"{channel_count} channel{plural}"

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(1)

        name_label = QLabel(name)
        name_label.setStyleSheet(f"color: {theme_colors.TEXT_DARK}; font-size: 13px; font-weight: 700;")
        layout.addWidget(name_label)
        detail_label = QLabel(detail_text)
        detail_label.setStyleSheet(f"color: {theme_colors.TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(detail_label)

        return widget

    def _refresh_buttons(self):
        has_selection = self.list_widget.currentItem() is not None
        self.delete_btn.setEnabled(has_selection)
        self.rename_btn.setEnabled(has_selection)
        if self.mode == "load":
            self.action_btn.setEnabled(has_selection)
        else:
            self.action_btn.setEnabled(bool(self.name_edit.text().strip()))

    def _set_preview(self, levels: dict[int, int]):
        # Only ON channels ever appear here - a config is "what to
        # activate", never "what to turn off" (see save_config_slot()'s
        # own comment on why), so there's no "Off" row to show at all,
        # just channels present or absent from the preview entirely.
        for address, lbl in enumerate(self.channel_labels):
            if address in levels:
                lbl.setText(f"CH{address + 1:02d}  {LEVEL_LABELS[levels[address]]}")
                lbl.setVisible(True)
            else:
                lbl.setVisible(False)
        self.empty_preview_label.setVisible(not levels)

    def _show_live_preview(self):
        levels = {
            address: state.data.last_level
            for address, state in self.app.channels.states.items()
            if state.data.output_on
        }
        self._set_preview(levels)

    def _on_selection_changed(self, current: QListWidgetItem, previous: QListWidgetItem = None):
        name = current.data(Qt.UserRole) if current is not None else None
        self._refresh_buttons()
        if self.mode == "save":
            if name:
                self.name_edit.setText(name)
                self.location_edit.setText(load_config_location(self.app.config, name))
            return
        if not name:
            self._set_preview({})
            return
        entries = load_config_slot(self.app.config, name)
        levels = {
            address: entry.get("last_level", 0)
            for address, entry in entries.items()
            if entry.get("output_on")
        }
        self._set_preview(levels)

    def _find_item_by_name(self, name: str) -> QListWidgetItem | None:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(Qt.UserRole) == name:
                return item
        return None

    def _on_rename_clicked(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        old_name = item.data(Qt.UserRole)
        new_name, ok = QInputDialog.getText(self, "Rename Config", "New name:", text=old_name)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        if not rename_config_slot(self.app.config, old_name, new_name):
            QMessageBox.warning(
                self, "Rename Config",
                f'A saved config named "{new_name}" already exists - pick a different name.',
            )
            return
        self._reload_slot_list()
        match = self._find_item_by_name(new_name)
        if match is not None:
            self.list_widget.setCurrentItem(match)
        if self.mode == "save" and self.name_edit.text().strip() == old_name:
            self.name_edit.setText(new_name)

    def _on_delete_clicked(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        name = item.data(Qt.UserRole)
        confirmed = QMessageBox.question(
            self, "Delete Config",
            f'Delete the saved config "{name}"? This can\'t be undone.',
        )
        if confirmed != QMessageBox.Yes:
            return
        delete_config_slot(self.app.config, name)
        self._reload_slot_list()
        if self.mode == "load":
            self._set_preview({})
        else:
            if self.name_edit.text().strip() == name:
                self.name_edit.clear()
        self._refresh_buttons()

    def _on_action_clicked(self):
        if self.mode == "load":
            item = self.list_widget.currentItem()
            if item is None:
                return
            self.result_name = item.data(Qt.UserRole)
            self.accept()
            return

        name = self.name_edit.text().strip()
        if not name:
            return
        existing = list_config_slots(self.app.config)
        if name in existing:
            confirmed = QMessageBox.question(
                self, "Overwrite Config",
                f'A saved config named "{name}" already exists - overwrite it?',
            )
            if confirmed != QMessageBox.Yes:
                return
        location = self.location_edit.text().strip()
        ok = save_config_slot(self.app.config, name, self.app.channels.states, location)
        if not ok:
            QMessageBox.warning(
                self, "Save Config",
                f"Maximum of {MAX_CONFIG_SLOTS} saved configs reached - "
                "overwrite an existing one instead, or pick a name that matches one.",
            )
            return
        self.result_name = name
        self.accept()
