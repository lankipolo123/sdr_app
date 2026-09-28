from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QListWidget,
    QLabel, QPushButton, QLineEdit, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt

from styles import theme_colors
from state.level_map import LEVEL_LABELS
from utils.config_slots import (
    list_config_slots, load_config_slot, save_config_slot, delete_config_slot, MAX_CONFIG_SLOTS,
)

MAX_CHANNELS = 16


def _level_color(level: int) -> str:
    return theme_colors.ACCENT_BLUE if level > 0 else theme_colors.TEXT_MUTED


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
        self.list_widget.currentTextChanged.connect(self._on_selection_changed)
        left_col.addWidget(self.list_widget, 1)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setStyleSheet(
            f"QPushButton {{ color: {theme_colors.STATUS_ERROR}; border: 1px solid {theme_colors.STATUS_ERROR}; "
            f"border-radius: 5px; padding: 4px 10px; background: transparent; }}"
            f"QPushButton:hover {{ background: {theme_colors.STATUS_ERROR}; color: white; }}"
            f"QPushButton:disabled {{ color: {theme_colors.TEXT_MUTED}; border-color: {theme_colors.BORDER_SUBTLE}; }}"
        )
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        left_col.addWidget(self.delete_btn)

        self.name_edit = None
        if mode == "save":
            self.name_edit = QLineEdit()
            self.name_edit.setPlaceholderText("Config name")
            self.name_edit.textChanged.connect(self._refresh_buttons)
            left_col.addWidget(self.name_edit)

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

        preview_grid = QGridLayout()
        preview_grid.setSpacing(4)
        self.channel_labels: list[QLabel] = []
        for address in range(MAX_CHANNELS):
            row_i, col_i = divmod(address, 2)
            lbl = QLabel(f"CH{address + 1:02d}  -")
            lbl.setStyleSheet(f"color: {theme_colors.TEXT_MUTED}; font-size: 12px;")
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
        self.list_widget.addItems(list_config_slots(self.app.config))
        self.count_label.setText(f"{self.list_widget.count()}/{MAX_CONFIG_SLOTS} saved")

    def _refresh_buttons(self):
        has_selection = self.list_widget.currentItem() is not None
        self.delete_btn.setEnabled(has_selection)
        if self.mode == "load":
            self.action_btn.setEnabled(has_selection)
        else:
            self.action_btn.setEnabled(bool(self.name_edit.text().strip()))

    def _set_preview(self, levels: dict[int, int]):
        for address, lbl in enumerate(self.channel_labels):
            level = levels.get(address, 0)
            lbl.setText(f"CH{address + 1:02d}  {LEVEL_LABELS[level]}")
            lbl.setStyleSheet(f"color: {_level_color(level)}; font-size: 12px; font-weight: {'700' if level else '400'};")

    def _show_live_preview(self):
        levels = {}
        for address, state in self.app.channels.states.items():
            d = state.data
            levels[address] = d.last_level if d.output_on else 0
        self._set_preview(levels)

    def _on_selection_changed(self, name: str):
        self._refresh_buttons()
        if self.mode == "save":
            if name:
                self.name_edit.setText(name)
            return
        if not name:
            self._set_preview({})
            return
        entries = load_config_slot(self.app.config, name)
        levels = {
            address: (entry.get("last_level", 0) if entry.get("output_on") else 0)
            for address, entry in entries.items()
        }
        self._set_preview(levels)

    def _on_delete_clicked(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        name = item.text()
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
            self.result_name = item.text()
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
        ok = save_config_slot(self.app.config, name, self.app.channels.states)
        if not ok:
            QMessageBox.warning(
                self, "Save Config",
                f"Maximum of {MAX_CONFIG_SLOTS} saved configs reached - "
                "overwrite an existing one instead, or pick a name that matches one.",
            )
            return
        self.result_name = name
        self.accept()
