import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from refacdir.lib.multi_display import SmartDialog
from refacdir.renamer_rule_generation import suggest_renamer_rules


class RenamerRuleSuggesterDialog(SmartDialog):
    """Suggests renamer rules by scanning filenames in a directory."""
    rule_applied = Signal(str)

    def __init__(self, parent=None, initial_directory: str = ""):
        super().__init__(
            parent=parent,
            position_parent=parent,
            title="Renamer Auto-Rule Suggestions",
            geometry="860x620",
            center=True,
        )
        self.setModal(True)
        self._result_rule = None
        self._suggestions = []

        layout = QVBoxLayout(self)
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
        layout.addLayout(form)

        analyze_btn = QPushButton("Analyze Filenames")
        analyze_btn.clicked.connect(self._analyze)
        layout.addWidget(analyze_btn)

        self.suggestion_list = QListWidget()
        self.suggestion_list.currentRowChanged.connect(self._on_selection_changed)
        layout.addWidget(self.suggestion_list, 1)

        self.details_label = QLabel("Pick a suggestion to preview details.")
        self.details_label.setWordWrap(True)
        layout.addWidget(self.details_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_selected)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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

    def _on_selection_changed(self, row: int):
        if row < 0 or row >= len(self._suggestions):
            self._result_rule = None
            return
        item = self._suggestions[row]
        self._result_rule = {
            "search_patterns": item["search_patterns"],
        }
        self.details_label.setText(
            f"Reason: {item.get('reason', 'n/a')}\n"
            f"Confidence: {item.get('confidence', 0)}%\n"
            f"Affected: {item.get('affected_files', 0)} files ({item.get('affected_percent', 0.0):.2f}%)\n"
            f"Pattern: {item['search_patterns']}\n"
            f"Top subdirs: {self._format_subdirs(item.get('subdirs', []))}"
        )

    def _accept_selected(self):
        if self._result_rule is None:
            QMessageBox.information(self, "Select Suggestion", "Pick a suggestion first.")
            return
        pattern = str(self._result_rule.get("search_patterns", "")).strip()
        if not pattern:
            QMessageBox.warning(self, "Invalid Suggestion", "Selected suggestion has no usable pattern.")
            return
        # Apply without closing so user can quickly pick multiple suggestions.
        self.rule_applied.emit(pattern)

    def set_directory(self, directory: str):
        if directory:
            self.directory_edit.setText(directory)

    def result_rule(self):
        return self._result_rule

    def _format_subdirs(self, subdirs: list[dict]) -> str:
        if not subdirs:
            return "n/a"
        return ", ".join(f"{item.get('subdir', '.')}: {item.get('count', 0)}" for item in subdirs)
