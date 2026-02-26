from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)
from PySide6.QtCore import Qt

from refacdir.lib.multi_display import SmartDialog


class DuplicateDetailsDialog(SmartDialog):
    """Detailed duplicate selection dialog."""

    def __init__(self, parent, groups: list[dict], title: str):
        super().__init__(
            parent=parent,
            position_parent=parent,
            title=title,
            geometry="980x680",
            center=True,
        )
        self.setModal(True)
        self._selected_files = []
        self._groups = groups
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.info = QLabel("Uncheck any files you do not want to remove.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.list_widget = QListWidget()
        for group_idx, group in enumerate(self._groups, start=1):
            keep_file = group.get("keep_file", "")
            obvious = group.get("obvious", False)
            header = QListWidgetItem(
                f"[Group {group_idx}] Keep: {keep_file} | Obvious: {'Yes' if obvious else 'No'}"
            )
            header.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(header)
            for file_path in group.get("remove_files", []):
                item = QListWidgetItem(f"  remove -> {file_path}")
                item.setData(Qt.UserRole, file_path)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.list_widget.addItem(item)
        layout.addWidget(self.list_widget, 1)

        button_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(lambda: self._set_all_checks(Qt.Checked))
        button_row.addWidget(self.select_all_btn)
        self.select_none_btn = QPushButton("Select None")
        self.select_none_btn.clicked.connect(lambda: self._set_all_checks(Qt.Unchecked))
        button_row.addWidget(self.select_none_btn)
        button_row.addStretch()
        layout.addLayout(button_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all_checks(self, state: Qt.CheckState):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            file_path = item.data(Qt.UserRole)
            if file_path:
                item.setCheckState(state)

    def _on_accept(self):
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            file_path = item.data(Qt.UserRole)
            if file_path and item.checkState() == Qt.Checked:
                selected.append(file_path)
        self._selected_files = selected
        self.accept()

    def selected_files(self) -> list[str]:
        return self._selected_files


class DuplicateSummaryDialog(SmartDialog):
    """Summary-first duplicate confirmation dialog."""

    def __init__(self, parent, payload: dict):
        super().__init__(
            parent=parent,
            position_parent=parent,
            title="Duplicate Removal Review",
            geometry="760x360",
            center=True,
        )
        self.setModal(True)
        self.payload = payload
        self.result_payload = {"action": "cancel", "files": []}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        total = self.payload.get("total_duplicate_files", 0)
        obvious = self.payload.get("obvious_count", 0)
        non_obvious = self.payload.get("non_obvious_count", 0)

        if total == 0:
            message = "No duplicates found."
        elif non_obvious == 0:
            message = (
                f"Do you want to remove all ({total}) duplicate files?\n"
                "All duplicates appear to be valid."
            )
        else:
            message = (
                f"Found {total} duplicate files.\n"
                f"- {obvious} are index-obvious duplicates.\n"
                f"- {non_obvious} are non-obvious by filename."
            )

        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)

        button_row = QHBoxLayout()
        remove_all_btn = QPushButton(f"Remove All ({total})")
        remove_all_btn.clicked.connect(self._on_remove_all)
        button_row.addWidget(remove_all_btn)

        review_all_btn = QPushButton(f"Review All ({total})")
        review_all_btn.clicked.connect(self._on_review_all)
        button_row.addWidget(review_all_btn)

        if non_obvious > 0:
            review_non_obvious_btn = QPushButton(f"Review Non-Obvious ({non_obvious})")
            review_non_obvious_btn.clicked.connect(self._on_review_non_obvious)
            button_row.addWidget(review_non_obvious_btn)

        button_row.addStretch()
        layout.addLayout(button_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _all_removals(self) -> list[str]:
        files = []
        for group in self.payload.get("groups", []):
            files.extend(group.get("remove_files", []))
        return files

    def _on_remove_all(self):
        self.result_payload = {"action": "remove_all", "files": self._all_removals()}
        self.accept()

    def _on_review_all(self):
        groups = self.payload.get("groups", [])
        dlg = DuplicateDetailsDialog(self, groups, "Review All Duplicate Files")
        if dlg.exec() == QDialog.Accepted:
            self.result_payload = {"action": "remove_selected", "files": dlg.selected_files()}
            self.accept()

    def _on_review_non_obvious(self):
        groups = [g for g in self.payload.get("groups", []) if not g.get("obvious", False)]
        dlg = DuplicateDetailsDialog(self, groups, "Review Non-Obvious Duplicate Files")
        if dlg.exec() == QDialog.Accepted:
            self.result_payload = {"action": "remove_selected", "files": dlg.selected_files()}
            self.accept()


def run_duplicate_review_dialog(parent, payload: dict) -> dict:
    dlg = DuplicateSummaryDialog(parent, payload)
    if dlg.exec() == QDialog.Accepted:
        return dlg.result_payload
    return {"action": "cancel", "files": []}
