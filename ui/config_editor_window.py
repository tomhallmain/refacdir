import copy
import os

import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
)

from refacdir.batch import ActionType, BatchArgs
from refacdir.config import Config
from refacdir.lib.multi_display import SmartWindow
from refacdir.utils.logger import setup_logger
from .config_action_dialogs import create_action_dialog

logger = setup_logger("config_editor")


class ConfigEditorWindow(SmartWindow):
    """Simple YAML config editor for batch action configs."""

    config_saved = Signal(str)

    def __init__(self, parent=None, app_actions=None):
        super().__init__(
            persistent_parent=parent,
            position_parent=parent,
            title="Config Editor",
            geometry="1200x800",
            center=True,
            window_flags=Qt.WindowType.Window,
        )
        self.app_actions = app_actions
        self.current_config_path = None
        self.current_config_data = self._new_config_template()

        self._build_ui()
        self.reload_config_list()

    def _build_ui(self):
        self.setMinimumSize(960, 640)
        layout = QVBoxLayout(self)

        top_buttons = QHBoxLayout()
        self.new_btn = QPushButton("New Config")
        self.new_btn.clicked.connect(self.new_config)
        top_buttons.addWidget(self.new_btn)

        self.open_btn = QPushButton("Open Selected")
        self.open_btn.clicked.connect(self.open_selected_config)
        top_buttons.addWidget(self.open_btn)

        self.reload_btn = QPushButton("Reload List")
        self.reload_btn.clicked.connect(self.reload_config_list)
        top_buttons.addWidget(self.reload_btn)
        top_buttons.addStretch()

        layout.addLayout(top_buttons)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left side: config files
        left_panel = QGroupBox("Config Files")
        left_layout = QVBoxLayout(left_panel)
        self.config_list = QListWidget()
        self.config_list.itemDoubleClicked.connect(lambda *_: self.open_selected_config())
        left_layout.addWidget(self.config_list)
        splitter.addWidget(left_panel)

        # Right side: editor
        right_panel = QGroupBox("Config Content")
        right_layout = QVBoxLayout(right_panel)

        info_form = QFormLayout()
        self.path_label = QLabel("(new config)")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_form.addRow("Path", self.path_label)

        self.will_run_checkbox = QCheckBox("Will run")
        self.will_run_checkbox.setChecked(True)
        info_form.addRow("Status", self.will_run_checkbox)
        right_layout.addLayout(info_form)

        action_group = QGroupBox("Actions")
        action_layout = QVBoxLayout(action_group)
        self.actions_list = QListWidget()
        self.actions_list.itemDoubleClicked.connect(lambda *_: self.edit_selected_action())
        action_layout.addWidget(self.actions_list)

        action_buttons = QGridLayout()
        self.add_action_btn = QPushButton("Add Action")
        self.add_action_btn.clicked.connect(self.add_action)
        action_buttons.addWidget(self.add_action_btn, 0, 0)

        self.edit_action_btn = QPushButton("Edit Action")
        self.edit_action_btn.clicked.connect(self.edit_selected_action)
        action_buttons.addWidget(self.edit_action_btn, 0, 1)

        self.remove_action_btn = QPushButton("Remove Action")
        self.remove_action_btn.clicked.connect(self.remove_selected_action)
        action_buttons.addWidget(self.remove_action_btn, 1, 0)

        self.move_action_up_btn = QPushButton("Move Up")
        self.move_action_up_btn.clicked.connect(lambda: self.move_selected_action(-1))
        action_buttons.addWidget(self.move_action_up_btn, 1, 1)

        self.move_action_down_btn = QPushButton("Move Down")
        self.move_action_down_btn.clicked.connect(lambda: self.move_selected_action(1))
        action_buttons.addWidget(self.move_action_down_btn, 2, 1)
        action_layout.addLayout(action_buttons)
        right_layout.addWidget(action_group)

        yaml_group = QGroupBox("Global YAML Blocks")
        yaml_layout = QVBoxLayout(yaml_group)
        yaml_layout.addWidget(QLabel("filename_mapping_functions"))
        self.filename_funcs_editor = QTextEdit()
        self.filename_funcs_editor.setMinimumHeight(120)
        yaml_layout.addWidget(self.filename_funcs_editor)
        yaml_layout.addWidget(QLabel("filetype_definitions"))
        self.filetypes_editor = QTextEdit()
        self.filetypes_editor.setMinimumHeight(120)
        yaml_layout.addWidget(self.filetypes_editor)
        right_layout.addWidget(yaml_group, 1)

        save_buttons = QHBoxLayout()
        save_buttons.addStretch()
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_current_config)
        save_buttons.addWidget(self.save_btn)
        self.save_as_btn = QPushButton("Save As")
        self.save_as_btn.clicked.connect(self.save_as_config)
        save_buttons.addWidget(self.save_as_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close)
        save_buttons.addWidget(self.cancel_btn)
        right_layout.addLayout(save_buttons)

        splitter.addWidget(right_panel)
        splitter.setSizes([300, 900])
        layout.addWidget(splitter, 1)

    def _new_config_template(self):
        return {
            "will_run": True,
            "filename_mapping_functions": [],
            "filetype_definitions": [],
            "actions": [],
        }

    def _config_abs_path(self, config_rel_path: str) -> str:
        return os.path.join(os.getcwd(), config_rel_path)

    def reload_config_list(self):
        self.config_list.clear()
        BatchArgs.setup_configs(recache=True)
        for config_path in sorted(BatchArgs.configs.keys()):
            item = QListWidgetItem(config_path)
            self.config_list.addItem(item)

    def open_selected_config(self):
        item = self.config_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Select Config", "Choose a config from the list first.")
            return
        self.load_config(item.text())

    def load_config(self, config_rel_path: str):
        abs_path = self._config_abs_path(config_rel_path)
        if not os.path.exists(abs_path):
            QMessageBox.warning(self, "Missing File", f"Config not found:\n{abs_path}")
            return
        try:
            with open(abs_path, "r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle) or {}
            if not isinstance(loaded, dict):
                raise ValueError("Top-level YAML must be a dictionary.")
            self.current_config_data = loaded
            self.current_config_path = config_rel_path
            self._sync_ui_from_data()
        except Exception as exc:
            logger.error(f"Failed loading config {abs_path}: {exc}")
            QMessageBox.critical(self, "Load Error", str(exc))

    def new_config(self):
        self.current_config_data = self._new_config_template()
        self.current_config_path = None
        self._sync_ui_from_data()

    def _sync_ui_from_data(self):
        self.path_label.setText(self.current_config_path or "(new config)")
        self.will_run_checkbox.setChecked(bool(self.current_config_data.get("will_run", True)))
        self.filename_funcs_editor.setPlainText(
            yaml.safe_dump(
                self.current_config_data.get("filename_mapping_functions", []),
                sort_keys=False,
                allow_unicode=False,
            )
        )
        self.filetypes_editor.setPlainText(
            yaml.safe_dump(
                self.current_config_data.get("filetype_definitions", []),
                sort_keys=False,
                allow_unicode=False,
            )
        )
        self._refresh_actions_list()

    def _refresh_actions_list(self):
        self.actions_list.clear()
        for idx, action in enumerate(self.current_config_data.get("actions", [])):
            action_type = action.get("type", "UNKNOWN")
            mapping_count = len(action.get("mappings", []))
            self.actions_list.addItem(f"{idx + 1}. {action_type} ({mapping_count} mapping(s))")

    def add_action(self):
        values = [a.value for a in ActionType]
        selected, ok = QInputDialog.getItem(self, "Choose Action Type", "Action Type", values, 0, False)
        if not ok or not selected:
            return
        action_type = ActionType[selected]
        dialog = create_action_dialog(self, action_type=action_type, action_data=None)
        if dialog.exec():
            action = dialog.result_action()
            if action:
                self.current_config_data.setdefault("actions", []).append(action)
                self._refresh_actions_list()

    def _selected_action_index(self):
        row = self.actions_list.currentRow()
        if row < 0:
            return None
        return row

    def edit_selected_action(self):
        idx = self._selected_action_index()
        if idx is None:
            QMessageBox.information(self, "Select Action", "Choose an action to edit.")
            return
        actions = self.current_config_data.setdefault("actions", [])
        action = actions[idx]
        try:
            action_type = ActionType[action["type"]]
        except Exception:
            QMessageBox.warning(self, "Invalid Action", f"Unsupported action type: {action.get('type')}")
            return
        dialog = create_action_dialog(self, action_type=action_type, action_data=copy.deepcopy(action))
        if dialog.exec():
            updated = dialog.result_action()
            if updated:
                actions[idx] = updated
                self._refresh_actions_list()
                self.actions_list.setCurrentRow(idx)

    def remove_selected_action(self):
        idx = self._selected_action_index()
        if idx is None:
            QMessageBox.information(self, "Select Action", "Choose an action to remove.")
            return
        actions = self.current_config_data.setdefault("actions", [])
        del actions[idx]
        self._refresh_actions_list()

    def move_selected_action(self, delta: int):
        idx = self._selected_action_index()
        if idx is None:
            return
        actions = self.current_config_data.setdefault("actions", [])
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(actions):
            return
        actions[idx], actions[new_idx] = actions[new_idx], actions[idx]
        self._refresh_actions_list()
        self.actions_list.setCurrentRow(new_idx)

    def _sync_data_from_ui(self):
        self.current_config_data["will_run"] = self.will_run_checkbox.isChecked()
        try:
            funcs = yaml.safe_load(self.filename_funcs_editor.toPlainText()) or []
            if not isinstance(funcs, list):
                raise ValueError("filename_mapping_functions must be a list.")
            self.current_config_data["filename_mapping_functions"] = funcs

            filetypes = yaml.safe_load(self.filetypes_editor.toPlainText()) or []
            if not isinstance(filetypes, list):
                raise ValueError("filetype_definitions must be a list.")
            self.current_config_data["filetype_definitions"] = filetypes
        except Exception as exc:
            raise ValueError(f"Invalid YAML block: {exc}") from exc

    def save_current_config(self):
        if self.current_config_path is None:
            return self.save_as_config()
        try:
            self._sync_data_from_ui()
            abs_path = self._config_abs_path(self.current_config_path)
            with open(abs_path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(self.current_config_data, handle, sort_keys=False, allow_unicode=False)
            self._after_save(self.current_config_path)
        except Exception as exc:
            logger.error(f"Failed saving config: {exc}")
            QMessageBox.critical(self, "Save Error", str(exc))

    def save_as_config(self):
        try:
            self._sync_data_from_ui()
        except Exception as exc:
            QMessageBox.critical(self, "Validation Error", str(exc))
            return

        default_dir = Config.CONFIGS_DIR_LOC
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Config As",
            os.path.join(default_dir, "new_config.yaml"),
            "YAML Files (*.yaml)",
        )
        if not path:
            return
        if not path.lower().endswith(".yaml"):
            path = f"{path}.yaml"
        try:
            with open(path, "w", encoding="utf-8") as handle:
                yaml.safe_dump(self.current_config_data, handle, sort_keys=False, allow_unicode=False)
            rel_path = os.path.relpath(path, os.getcwd()).replace("\\", "/")
            self.current_config_path = rel_path
            self._after_save(rel_path)
        except Exception as exc:
            logger.error(f"Failed save-as config: {exc}")
            QMessageBox.critical(self, "Save As Error", str(exc))

    def _after_save(self, config_rel_path: str):
        self.path_label.setText(config_rel_path)
        self.reload_config_list()
        self.config_saved.emit(config_rel_path)
        if self.app_actions and hasattr(self.app_actions, "refresh_configs"):
            try:
                self.app_actions.refresh_configs()
            except Exception as exc:
                logger.warning(f"refresh_configs callback failed: {exc}")
        QMessageBox.information(self, "Saved", f"Saved config:\n{config_rel_path}")
