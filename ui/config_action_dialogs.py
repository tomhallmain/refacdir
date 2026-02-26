import copy
import os
import yaml

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from refacdir.batch import ActionType
from refacdir.lib.multi_display import SmartDialog
from .renamer_rule_suggester_dialog import RenamerRuleSuggesterDialog


def _default_action_dict(action_type: ActionType) -> dict:
    return {
        "type": action_type.value,
        "mappings": [],
    }


class MappingPropertyRow(QWidget):
    """Row widget for generic mapping key/value editing."""

    def __init__(self, allowed_keys: list[str], key: str = "", value=None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.key_combo = QComboBox()
        self.key_combo.setEditable(True)
        self.key_combo.addItems(allowed_keys)
        if key:
            self.key_combo.setCurrentText(key)
        layout.addWidget(self.key_combo, 2)

        self.value_edit = QLineEdit()
        if value is not None:
            dumped = yaml.safe_dump(value, sort_keys=False, allow_unicode=False).strip()
            self.value_edit.setText(dumped)
        layout.addWidget(self.value_edit, 5)

        self.remove_btn = QPushButton("Remove")
        layout.addWidget(self.remove_btn)

    def key(self) -> str:
        return self.key_combo.currentText().strip()

    def value(self):
        text = self.value_edit.text().strip()
        if text == "":
            return ""
        try:
            return yaml.safe_load(text)
        except Exception:
            return text


class BaseActionDialog(SmartDialog):
    """Shared action editor with mapping list + mapping detail panel."""

    def __init__(self, parent, action_type: ActionType, action_data: dict | None = None):
        super().__init__(
            parent=parent,
            position_parent=parent,
            title=f"Edit {action_type.value} Action",
            geometry="980x700",
            center=True,
        )
        self.setModal(True)
        self._action_type = action_type
        self._result = None
        self._selected_mapping_index = None
        self._mapping_property_rows: list[MappingPropertyRow] = []

        data = copy.deepcopy(action_data) if action_data else _default_action_dict(action_type)
        data["type"] = action_type.value
        self._mappings = data.get("mappings", [])

        self._build_ui()
        self._refresh_mapping_list()

    def hint_text(self) -> str:
        return "Edit mappings using the list and details panel."

    def property_key_options(self) -> list[str]:
        # TODO: Derive these options from centralized schemas tied to BatchJob
        # construct_* methods so UI keys stay synchronized with backend fields.
        return []

    def default_mapping(self) -> dict:
        return {"name": f"{self._action_type.value.lower()} mapping"}

    def mapping_summary(self, mapping: dict) -> str:
        name = mapping.get("name", "(unnamed)")
        return f"{name} ({len(mapping.keys())} key(s))"

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.type_combo = QComboBox()
        self.type_combo.addItem(self._action_type.value)
        self.type_combo.setEnabled(False)
        form.addRow("Action Type", self.type_combo)

        self.hint_label = QLabel(self.hint_text())
        self.hint_label.setWordWrap(True)
        form.addRow("Notes", self.hint_label)
        layout.addLayout(form)

        body_layout = QHBoxLayout()

        left_group = QGroupBox("Mappings")
        left_layout = QVBoxLayout(left_group)
        self.mapping_list = QListWidget()
        self.mapping_list.currentRowChanged.connect(self._on_mapping_selected)
        left_layout.addWidget(self.mapping_list)

        map_btns = QHBoxLayout()
        self.add_mapping_btn = QPushButton("Add")
        self.add_mapping_btn.clicked.connect(self._on_add_mapping)
        map_btns.addWidget(self.add_mapping_btn)
        self.remove_mapping_btn = QPushButton("Remove")
        self.remove_mapping_btn.clicked.connect(self._on_remove_mapping)
        map_btns.addWidget(self.remove_mapping_btn)
        left_layout.addLayout(map_btns)
        body_layout.addWidget(left_group, 2)

        right_group = QGroupBox("Mapping Details")
        right_layout = QVBoxLayout(right_group)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll.setWidget(self.scroll_content)
        self.detail_layout = QVBoxLayout(self.scroll_content)
        right_layout.addWidget(self.scroll, 1)
        body_layout.addWidget(right_group, 5)

        layout.addLayout(body_layout, 1)

        self._build_mapping_detail_widgets()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_mapping_detail_widgets(self):
        self.detail_form = QFormLayout()
        self.name_edit = QLineEdit()
        self.detail_form.addRow("Name", self.name_edit)
        self.detail_layout.addLayout(self.detail_form)

        props_group = QGroupBox("Properties")
        props_layout = QVBoxLayout(props_group)
        self.props_container = QWidget()
        self.props_container_layout = QVBoxLayout(self.props_container)
        self.props_container_layout.setContentsMargins(0, 0, 0, 0)
        props_layout.addWidget(self.props_container)

        add_prop_btn = QPushButton("Add Property")
        add_prop_btn.clicked.connect(self._on_add_property_row)
        props_layout.addWidget(add_prop_btn)
        self.detail_layout.addWidget(props_group)

        detail_buttons = QHBoxLayout()
        self.save_mapping_btn = QPushButton("Save Mapping")
        self.save_mapping_btn.clicked.connect(self._on_save_mapping)
        detail_buttons.addWidget(self.save_mapping_btn)
        detail_buttons.addStretch()
        self.detail_layout.addLayout(detail_buttons)
        self.detail_layout.addStretch()

    def _clear_property_rows(self):
        for row in self._mapping_property_rows:
            row.setParent(None)
            row.deleteLater()
        self._mapping_property_rows = []

    def _on_add_property_row(self, key: str = "", value=None):
        row = MappingPropertyRow(self.property_key_options(), key=key, value=value, parent=self.props_container)
        row.remove_btn.clicked.connect(lambda: self._remove_property_row(row))
        self.props_container_layout.addWidget(row)
        self._mapping_property_rows.append(row)

    def _remove_property_row(self, row: MappingPropertyRow):
        if row in self._mapping_property_rows:
            self._mapping_property_rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    def _refresh_mapping_list(self):
        self.mapping_list.clear()
        for mapping in self._mappings:
            self.mapping_list.addItem(self.mapping_summary(mapping))
        if self._mappings:
            row = 0 if self._selected_mapping_index is None else min(self._selected_mapping_index, len(self._mappings) - 1)
            self.mapping_list.setCurrentRow(row)
        else:
            self._selected_mapping_index = None
            self.name_edit.clear()
            self._clear_property_rows()

    def _on_mapping_selected(self, row: int):
        if row < 0 or row >= len(self._mappings):
            self._selected_mapping_index = None
            return
        self._selected_mapping_index = row
        self._load_mapping_to_editor(self._mappings[row])

    def _load_mapping_to_editor(self, mapping: dict):
        self.name_edit.setText(str(mapping.get("name", "")))
        self._clear_property_rows()
        for key, value in mapping.items():
            if key == "name":
                continue
            self._on_add_property_row(key=key, value=value)

    def _build_mapping_from_editor(self) -> dict:
        mapping = {"name": self.name_edit.text().strip()}
        if mapping["name"] == "":
            raise ValueError("Mapping name is required.")

        for row in self._mapping_property_rows:
            key = row.key()
            if key == "":
                continue
            mapping[key] = row.value()
        return mapping

    def _on_save_mapping(self):
        if self._selected_mapping_index is None:
            QMessageBox.information(self, "Select Mapping", "Choose a mapping to save.")
            return
        try:
            updated = self._build_mapping_from_editor()
            self._mappings[self._selected_mapping_index] = updated
            self._refresh_mapping_list()
            self.mapping_list.setCurrentRow(self._selected_mapping_index)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Mapping", str(exc))

    def _on_add_mapping(self):
        self._mappings.append(self.default_mapping())
        self._selected_mapping_index = len(self._mappings) - 1
        self._refresh_mapping_list()
        self.mapping_list.setCurrentRow(self._selected_mapping_index)

    def _on_remove_mapping(self):
        row = self.mapping_list.currentRow()
        if row < 0 or row >= len(self._mappings):
            return
        del self._mappings[row]
        self._selected_mapping_index = None
        self._refresh_mapping_list()

    def _validate_unique_mapping_names(self):
        names = []
        for mapping in self._mappings:
            name = str(mapping.get("name", "")).strip()
            if not name:
                raise ValueError("All mappings must have a name.")
            names.append(name)
        if len(set(names)) != len(names):
            raise ValueError("Mapping names must be unique within the action.")

    def _on_accept(self):
        try:
            if self._selected_mapping_index is not None:
                # Persist any unsaved detail edits for currently selected mapping.
                self._mappings[self._selected_mapping_index] = self._build_mapping_from_editor()
            self._validate_unique_mapping_names()
            self._result = {
                "type": self._action_type.value,
                "mappings": self._mappings,
            }
            self.accept()
        except Exception as exc:
            self.hint_label.setText(f"Validation failed: {exc}")
            self.hint_label.setStyleSheet("color: #f44336;")

    def result_action(self) -> dict | None:
        return self._result


class BackupActionDialog(BaseActionDialog):
    def hint_text(self) -> str:
        return "Backup mappings may include backup_mappings list and options."

    def property_key_options(self) -> list[str]:
        # TODO: Sync this list with BatchJob.construct_backup schema metadata.
        return [
            "warn_duplicates",
            "overwrite",
            "test",
            "skip_confirm",
            "backup_mappings",
        ]


class RenamerActionDialog(BaseActionDialog):
    """Structured renamer mapping editor with nested rename rules."""

    def hint_text(self) -> str:
        return "Each mapping defines function, locations, rename rules, and optional flags."

    def default_mapping(self) -> dict:
        return {
            "name": "New renamer mapping",
            "function": "rename_by_ctime",
            "locations": [{"root": "{{USER_HOME}}\\Downloads"}],
            "mappings": [],
            "recursive": True,
            "make_dirs": True,
            "find_unused_filenames": False,
        }

    def mapping_summary(self, mapping: dict) -> str:
        name = mapping.get("name", "(unnamed)")
        rules = len(mapping.get("mappings", []))
        locations = len(mapping.get("locations", []))
        return f"{name} ({rules} rule(s), {locations} location(s))"

    def _build_mapping_detail_widgets(self):
        self.detail_form = QFormLayout()
        self.name_edit = QLineEdit()
        self.detail_form.addRow("Name", self.name_edit)

        self.function_combo = QComboBox()
        self.function_combo.setEditable(True)
        self.function_combo.addItems(["rename_by_ctime", "move_files"])
        self.detail_form.addRow("Function", self.function_combo)
        self.detail_layout.addLayout(self.detail_form)

        options_group = QGroupBox("Options")
        options_layout = QGridLayout(options_group)
        self.recursive_check = QCheckBox("recursive")
        self.test_check = QCheckBox("test")
        self.skip_confirm_check = QCheckBox("skip_confirm")
        self.make_dirs_check = QCheckBox("make_dirs")
        self.find_unused_check = QCheckBox("find_unused_filenames")
        options_layout.addWidget(self.recursive_check, 0, 0)
        options_layout.addWidget(self.test_check, 0, 1)
        options_layout.addWidget(self.skip_confirm_check, 1, 0)
        options_layout.addWidget(self.make_dirs_check, 1, 1)
        options_layout.addWidget(self.find_unused_check, 2, 0)
        self.detail_layout.addWidget(options_group)

        locations_group = QGroupBox("Locations (one root path per line)")
        locations_layout = QVBoxLayout(locations_group)
        self.locations_editor = QTextEdit()
        self.locations_editor.setMinimumHeight(110)
        locations_layout.addWidget(self.locations_editor)
        self.detail_layout.addWidget(locations_group)

        rules_group = QGroupBox("Rename Rules")
        rules_layout = QVBoxLayout(rules_group)
        self.rules_list = QListWidget()
        self.rules_list.currentRowChanged.connect(self._on_rule_selected)
        rules_layout.addWidget(self.rules_list)

        rule_btn_row = QHBoxLayout()
        self.upsert_rule_btn = QPushButton("Add / Update Rule")
        self.upsert_rule_btn.clicked.connect(self._on_upsert_rule)
        rule_btn_row.addWidget(self.upsert_rule_btn)
        self.remove_rule_btn = QPushButton("Remove Rule")
        self.remove_rule_btn.clicked.connect(self._on_remove_rule)
        rule_btn_row.addWidget(self.remove_rule_btn)
        self.new_rule_btn = QPushButton("New Rule Draft")
        self.new_rule_btn.clicked.connect(self._on_new_rule_draft)
        rule_btn_row.addWidget(self.new_rule_btn)
        self.suggest_rules_btn = QPushButton("Suggest Rules...")
        self.suggest_rules_btn.clicked.connect(self._open_rule_suggester)
        rule_btn_row.addWidget(self.suggest_rules_btn)
        rules_layout.addLayout(rule_btn_row)

        rule_editor_form = QFormLayout()
        self.rule_search_edit = QLineEdit()
        self.rule_search_edit.setPlaceholderText("pattern or comma-separated patterns")
        rule_editor_form.addRow("search_patterns", self.rule_search_edit)
        self.rule_tag_edit = QLineEdit()
        self.rule_tag_edit.setPlaceholderText("rename_tag")
        rule_editor_form.addRow("rename_tag", self.rule_tag_edit)
        rules_layout.addLayout(rule_editor_form)

        self.detail_layout.addWidget(rules_group, 1)

        detail_buttons = QHBoxLayout()
        self.save_mapping_btn = QPushButton("Save Mapping")
        self.save_mapping_btn.clicked.connect(self._on_save_mapping)
        detail_buttons.addWidget(self.save_mapping_btn)
        detail_buttons.addStretch()
        self.detail_layout.addLayout(detail_buttons)

        self._rules: list[dict] = []
        self._selected_rule_index = None
        self._suggester_dialog = None
        self._loaded_mapping_keys = set()

    def _load_mapping_to_editor(self, mapping: dict):
        self._loaded_mapping_keys = set(mapping.keys())
        self.name_edit.setText(str(mapping.get("name", "")))
        self.function_combo.setCurrentText(str(mapping.get("function", "rename_by_ctime")))

        self.recursive_check.setChecked(bool(mapping.get("recursive", True)))
        self.test_check.setChecked(bool(mapping.get("test", False)))
        self.skip_confirm_check.setChecked(bool(mapping.get("skip_confirm", False)))
        self.make_dirs_check.setChecked(bool(mapping.get("make_dirs", True)))
        self.find_unused_check.setChecked(bool(mapping.get("find_unused_filenames", False)))

        roots = []
        for location in mapping.get("locations", []):
            if isinstance(location, dict) and "root" in location:
                roots.append(str(location["root"]))
            elif isinstance(location, str):
                roots.append(location)
        self.locations_editor.setPlainText("\n".join(roots))

        self._rules = copy.deepcopy(mapping.get("mappings", []))
        self._refresh_rules_list()

    def _build_mapping_from_editor(self) -> dict:
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Mapping name is required.")

        locations = []
        for line in self.locations_editor.toPlainText().splitlines():
            root = line.strip()
            if root:
                locations.append({"root": root})

        if not locations:
            raise ValueError("At least one location root is required.")

        if self._selected_rule_index is not None and 0 <= self._selected_rule_index < len(self._rules):
            # Persist active rule edits if user changed fields but forgot save.
            self._rules[self._selected_rule_index] = self._build_rule_from_editor()

        if not self._rules:
            raise ValueError("At least one rename rule is required.")

        mapping = {
            "name": name,
            "function": self.function_combo.currentText().strip() or "rename_by_ctime",
            "mappings": self._rules,
            "locations": locations,
            "recursive": self.recursive_check.isChecked(),
            "make_dirs": self.make_dirs_check.isChecked(),
            "find_unused_filenames": self.find_unused_check.isChecked(),
        }

        # Preserve global behavior for test/skip_confirm when unset.
        # If key existed in loaded mapping, keep explicit value.
        # Otherwise, only write when checked True (explicit override).
        test_checked = self.test_check.isChecked()
        skip_checked = self.skip_confirm_check.isChecked()

        if "test" in self._loaded_mapping_keys or test_checked:
            mapping["test"] = test_checked
        if "skip_confirm" in self._loaded_mapping_keys or skip_checked:
            mapping["skip_confirm"] = skip_checked

        return mapping

    def _refresh_rules_list(self):
        self.rules_list.clear()
        for idx, rule in enumerate(self._rules):
            patterns = rule.get("search_patterns", "")
            if isinstance(patterns, list):
                pattern_preview = f"{len(patterns)} pattern(s)"
            else:
                pattern_preview = str(patterns)[:35]
            tag = str(rule.get("rename_tag", ""))
            self.rules_list.addItem(f"{idx + 1}. {tag} <- {pattern_preview}")
        if self._rules:
            row = 0 if self._selected_rule_index is None else min(self._selected_rule_index, len(self._rules) - 1)
            self.rules_list.setCurrentRow(row)
        else:
            self._selected_rule_index = None
            self.rule_search_edit.clear()
            self.rule_tag_edit.clear()

    def _on_rule_selected(self, row: int):
        if row < 0 or row >= len(self._rules):
            self._selected_rule_index = None
            return
        self._selected_rule_index = row
        rule = self._rules[row]
        patterns = rule.get("search_patterns", "")
        if isinstance(patterns, list):
            self.rule_search_edit.setText(", ".join(str(p) for p in patterns))
        else:
            self.rule_search_edit.setText(str(patterns))
        self.rule_tag_edit.setText(str(rule.get("rename_tag", "")))

    def _on_new_rule_draft(self):
        self._selected_rule_index = None
        self.rules_list.clearSelection()
        self.rule_search_edit.clear()
        self.rule_tag_edit.clear()

    def _build_rule_from_editor(self) -> dict:
        patterns_text = self.rule_search_edit.text().strip()
        if not patterns_text:
            raise ValueError("search_patterns is required.")
        rename_tag = self.rule_tag_edit.text().strip()
        if not rename_tag:
            raise ValueError("rename_tag is required.")

        if "," in patterns_text:
            patterns = [part.strip() for part in patterns_text.split(",") if part.strip()]
        else:
            patterns = patterns_text

        return {
            "search_patterns": patterns,
            "rename_tag": rename_tag,
        }

    def _on_upsert_rule(self):
        try:
            built = self._build_rule_from_editor()
            if self._selected_rule_index is None:
                self._rules.append(built)
                self._selected_rule_index = len(self._rules) - 1
            else:
                self._rules[self._selected_rule_index] = built
            self._refresh_rules_list()
            self.rules_list.setCurrentRow(self._selected_rule_index)
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Rule", str(exc))

    def _on_remove_rule(self):
        row = self.rules_list.currentRow()
        if row < 0 or row >= len(self._rules):
            return
        del self._rules[row]
        self._selected_rule_index = None
        self._refresh_rules_list()

    def _resolve_initial_suggester_directory(self) -> str:
        lines = [line.strip() for line in self.locations_editor.toPlainText().splitlines() if line.strip()]
        if not lines:
            return os.getcwd()
        root = lines[0]
        root = root.replace("{{USER_HOME}}", os.path.expanduser("~"))
        return root

    def _open_rule_suggester(self):
        initial_dir = self._resolve_initial_suggester_directory()
        if self._suggester_dialog is None:
            self._suggester_dialog = RenamerRuleSuggesterDialog(
                parent=self,
                initial_directory=initial_dir,
            )
            self._suggester_dialog.setModal(False)
            self._suggester_dialog.rule_applied.connect(self._append_suggested_pattern)
        else:
            self._suggester_dialog.set_directory(initial_dir)

        self._suggester_dialog.show()
        self._suggester_dialog.raise_()
        self._suggester_dialog.activateWindow()

    def _append_suggested_pattern(self, pattern: str):
        pattern = pattern.strip()
        if not pattern:
            return
        current = self.rule_search_edit.text().strip()
        if not current:
            self.rule_search_edit.setText(pattern)
            return

        existing = [part.strip() for part in current.split(",") if part.strip()]
        if pattern in existing:
            return
        self.rule_search_edit.setText(f"{current}, {pattern}")


class DuplicateRemoverActionDialog(BaseActionDialog):
    def hint_text(self) -> str:
        return "Duplicate remover mappings usually contain source dirs and exclusion settings."

    def property_key_options(self) -> list[str]:
        # TODO: Sync this list with BatchJob.construct_duplicate_remover metadata.
        return [
            "source_dirs",
            "select_for_folder_depth",
            "match_dir",
            "recursive",
            "exclude_dirs",
            "preferred_delete_dirs",
        ]


class DirectoryObserverActionDialog(BaseActionDialog):
    def hint_text(self) -> str:
        return "Directory observer mappings usually contain sortable/extra/parent dirs and file_types."

    def property_key_options(self) -> list[str]:
        # TODO: Sync this list with BatchJob.construct_directory_observer metadata.
        return [
            "sortable_dirs",
            "extra_dirs",
            "parent_dirs",
            "exclude_dirs",
            "file_types",
        ]


class DirectoryFlattenerActionDialog(BaseActionDialog):
    def hint_text(self) -> str:
        return "Directory flattener mappings usually include location and search_patterns."

    def property_key_options(self) -> list[str]:
        # TODO: Sync this list with BatchJob.construct_directory_flattener metadata.
        return [
            "test",
            "search_patterns",
            "location",
            "skip_confirm",
        ]


class ImageCategorizerActionDialog(BaseActionDialog):
    def hint_text(self) -> str:
        return "Image categorizer mappings include source_dir, categories, and filters."

    def property_key_options(self) -> list[str]:
        # TODO: Sync this list with BatchJob.construct_image_categorizer metadata.
        return [
            "test",
            "source_dir",
            "file_types",
            "categories",
            "recursive",
            "exclude_dirs",
            "skip_confirm",
        ]


class BackupActionDialog(BaseActionDialog):
    def hint_text(self) -> str:
        return "Backup mappings include backup_mappings plus optional flags."

    def property_key_options(self) -> list[str]:
        return [
            "warn_duplicates",
            "overwrite",
            "test",
            "skip_confirm",
            "backup_mappings",
        ]


def create_action_dialog(parent, action_type: ActionType, action_data: dict | None = None) -> BaseActionDialog:
    dialog_map = {
        ActionType.BACKUP: BackupActionDialog,
        ActionType.RENAMER: RenamerActionDialog,
        ActionType.DUPLICATE_REMOVER: DuplicateRemoverActionDialog,
        ActionType.DIRECTORY_OBSERVER: DirectoryObserverActionDialog,
        ActionType.DIRECTORY_FLATTENER: DirectoryFlattenerActionDialog,
        ActionType.IMAGE_CATEGORIZER: ImageCategorizerActionDialog,
    }
    dialog_cls = dialog_map.get(action_type, BaseActionDialog)
    return dialog_cls(parent=parent, action_type=action_type, action_data=action_data)
