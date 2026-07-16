import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from refacdir.lib.multi_display import SmartDialog
from refacdir.renamer_rule_generation import common_pattern_presets, suggest_renamer_rules


class RenamerRuleSuggesterDialog(SmartDialog):
    """
    Suggests renamer rules two ways:
    - Common Patterns: a static catalog of well-known filename shapes (e.g. a
      short integer basename), available immediately with no directory needed.
    - Detected From Files: scans a chosen directory for repeated filename shapes.

    Either way, nothing is applied to the mapping being edited until the user
    picks a suggestion here and clicks OK.
    """

    rule_applied = Signal(dict)

    def __init__(self, parent=None, initial_directory: str = ""):
        super().__init__(
            parent=parent,
            position_parent=parent,
            title="Renamer Auto-Rule Suggestions",
            geometry="860x680",
            center=True,
        )
        self.setModal(True)
        self._result_rule = None
        self._suggestions = []
        self._presets = common_pattern_presets()

        layout = QVBoxLayout(self)

        presets_group = QGroupBox("Common Patterns (no directory needed)")
        presets_layout = QVBoxLayout(presets_group)
        self.preset_list = QListWidget()
        self.preset_list.currentRowChanged.connect(self._on_preset_selection_changed)
        presets_layout.addWidget(self.preset_list)
        layout.addWidget(presets_group)
        self._populate_presets()

        detected_group = QGroupBox("Detected From Files")
        detected_layout = QVBoxLayout(detected_group)
        form = QFormLayout()

        dir_row = QHBoxLayout()
        self.directory_edit = QLineEdit(initial_directory)
        dir_row.addWidget(self.directory_edit, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_directory)
        dir_row.addWidget(browse_btn)
        form.addRow("Directory", dir_row)

        self.recursive_check = QCheckBox("Scan recursively")
        self.recursive_check.setChecked(False)
        form.addRow("Options", self.recursive_check)
        detected_layout.addLayout(form)

        analyze_btn = QPushButton("Analyze Filenames")
        analyze_btn.clicked.connect(self._analyze)
        detected_layout.addWidget(analyze_btn)

        self.suggestion_list = QListWidget()
        self.suggestion_list.currentRowChanged.connect(self._on_selection_changed)
        detected_layout.addWidget(self.suggestion_list, 1)
        layout.addWidget(detected_group, 1)

        self.details_label = QLabel("Pick a suggestion to preview details.")
        self.details_label.setWordWrap(True)
        layout.addWidget(self.details_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_selected)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_presets(self):
        self.preset_list.clear()
        for preset in self._presets:
            self.preset_list.addItem(f"{preset['name']} — {preset['search_patterns']}")

    def _browse_directory(self):
        start_dir = self.directory_edit.text().strip() or os.getcwd()
        selected = QFileDialog.getExistingDirectory(self, "Select Directory", start_dir)
        if selected:
            self.directory_edit.setText(selected)

    def _analyze(self):
        directory = self.directory_edit.text().strip()
        if not directory:
            QMessageBox.information(self, "Directory Required", "Please choose a directory first.")
            return
        if not os.path.isdir(directory):
            QMessageBox.warning(self, "Invalid Directory", f"Not a valid directory:\n{directory}")
            return

        self._suggestions = suggest_renamer_rules(
            directory=directory,
            recursive=self.recursive_check.isChecked(),
            max_rules=16,
        )
        self.suggestion_list.clear()
        if not self._suggestions:
            self.details_label.setText("No strong filename patterns detected.")
            return

        for idx, item in enumerate(self._suggestions):
            pattern = item["search_patterns"]
            affected = item.get("affected_files", 0)
            pct = item.get("affected_percent", 0.0)
            confidence = item.get("confidence", 0)
            self.suggestion_list.addItem(
                f"{idx + 1}. [{confidence}%] {pattern}  ({affected} files, {pct:.1f}%)"
            )
        self.suggestion_list.setCurrentRow(0)

    def _on_preset_selection_changed(self, row: int):
        if row < 0 or row >= len(self._presets):
            if self._result_rule is None or self._result_rule.get("_source") == "preset":
                self._result_rule = None
            return
        self._deselect(self.suggestion_list)
        preset = self._presets[row]
        self._result_rule = {
            "search_patterns": preset["search_patterns"],
            "rename_tag": preset.get("rename_tag", ""),
            "_source": "preset",
        }
        self.details_label.setText(
            f"Reason: {preset.get('reason', 'n/a')}\n"
            f"Pattern: {preset['search_patterns']}\n"
            f"Suggested rename_tag: {preset.get('rename_tag', 'n/a')}\n"
            f"Suggested function: {preset.get('function_hint', 'n/a')} "
            "(set this yourself in the Function dropdown; it's not applied automatically)"
        )

    def _on_selection_changed(self, row: int):
        if row < 0 or row >= len(self._suggestions):
            if self._result_rule is None or self._result_rule.get("_source") == "detected":
                self._result_rule = None
            return
        self._deselect(self.preset_list)
        item = self._suggestions[row]
        self._result_rule = {
            "search_patterns": item["search_patterns"],
            "_source": "detected",
        }
        self.details_label.setText(
            f"Reason: {item.get('reason', 'n/a')}\n"
            f"Confidence: {item.get('confidence', 0)}%\n"
            f"Affected: {item.get('affected_files', 0)} files ({item.get('affected_percent', 0.0):.2f}%)\n"
            f"Pattern: {item['search_patterns']}\n"
            f"Top subdirs: {self._format_subdirs(item.get('subdirs', []))}"
        )

    @staticmethod
    def _deselect(list_widget: QListWidget):
        """Clear the other list's selection without re-entering its changed handler."""
        list_widget.blockSignals(True)
        list_widget.setCurrentRow(-1)
        list_widget.clearSelection()
        list_widget.blockSignals(False)

    def _accept_selected(self):
        if self._result_rule is None:
            QMessageBox.information(self, "Select Suggestion", "Pick a suggestion first.")
            return
        pattern = str(self._result_rule.get("search_patterns", "")).strip()
        if not pattern:
            QMessageBox.warning(self, "Invalid Suggestion", "Selected suggestion has no usable pattern.")
            return
        # Apply without closing so user can quickly pick multiple suggestions.
        payload = {k: v for k, v in self._result_rule.items() if k != "_source"}
        self.rule_applied.emit(payload)

    def set_directory(self, directory: str):
        if directory:
            self.directory_edit.setText(directory)

    def result_rule(self):
        return self._result_rule

    def _format_subdirs(self, subdirs: list[dict]) -> str:
        if not subdirs:
            return "n/a"
        return ", ".join(f"{item.get('subdir', '.')}: {item.get('count', 0)}" for item in subdirs)
