"""The Replace Paths dialog: change or remove a directory path in every config."""

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from refacdir import path_replace
from refacdir.lib.multi_display import SmartDialog
from refacdir.utils.translations import _, localized_str

_HIT_ID_ROLE = Qt.ItemDataRole.UserRole
_MISSING_PATH_ROLE = Qt.ItemDataRole.UserRole + 1


class PathReplaceDialog(SmartDialog):
    def __init__(
        self,
        parent,
        is_run_active: Callable[[], bool],
        unsaved_configs: Callable[[], set],
        on_applied: Optional[Callable[[list], None]] = None,
    ):
        """
        :param is_run_active: True while a batch run is running or queued; applying is refused then.
        :param unsaved_configs: config keys open in the config editor with unsaved changes.
        :param on_applied: called with the written config keys after an apply or undo.
        """
        super().__init__(
            parent=parent,
            position_parent=parent,
            title=_("Replace Paths"),
            geometry="1100x700",
            center=True,
        )
        self._is_run_active = is_run_active
        self._unsaved_configs = unsaved_configs
        self._on_applied = on_applied
        self._plan = None
        self._build_ui()
        self._on_mode_changed()
        self._update_buttons()

    # ----- layout -----

    def _build_ui(self):
        layout = QVBoxLayout(self)

        hint = QLabel(_(
            "Changes a directory path, and every path under it, in all config files at once "
            "(enabled or not). Only directory fields are changed. Search first, check the "
            "hits, then apply; each changed file is backed up and the last change can be undone."
        ))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        mode_row = QHBoxLayout()
        self.replace_radio = QRadioButton(_("Replace"))
        self.remove_radio = QRadioButton(_("Remove"))
        self.replace_radio.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.replace_radio)
        self._mode_group.addButton(self.remove_radio)
        self.replace_radio.toggled.connect(self._on_mode_changed)
        mode_row.addWidget(self.replace_radio)
        mode_row.addWidget(self.remove_radio)
        mode_row.addStretch()
        form.addRow(_("Mode"), mode_row)

        self.old_path_edit = QLineEdit()
        form.addRow(_("Old path"), self._with_browse(self.old_path_edit))
        self.new_path_edit = QLineEdit()
        self.new_path_row = self._with_browse(self.new_path_edit)
        form.addRow(_("New path"), self.new_path_row)
        layout.addLayout(form)

        search_row = QHBoxLayout()
        self.search_btn = QPushButton(_("Search"))
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)
        search_row.addStretch()
        layout.addLayout(search_row)

        self.tabs = QTabWidget()
        self.hits_tree = QTreeWidget()
        self.hits_tree.setHeaderLabels(
            [_("Config"), _("Action"), _("Mapping"), _("Field"), _("Old value"), _("New value"), _("Note")]
        )
        self.hits_tree.setRootIsDecorated(False)
        self.hits_tree.itemChanged.connect(lambda *_args: self._update_buttons())
        self.tabs.addTab(self.hits_tree, _("Hits"))

        missing_tab = QWidget()
        missing_layout = QVBoxLayout(missing_tab)
        missing_buttons = QHBoxLayout()
        self.find_missing_btn = QPushButton(_("Find Missing Directories"))
        self.find_missing_btn.clicked.connect(self._on_find_missing)
        missing_buttons.addWidget(self.find_missing_btn)
        self.use_for_replace_btn = QPushButton(_("Replace This Path..."))
        self.use_for_replace_btn.clicked.connect(lambda: self._use_missing_path(path_replace.MODE_REPLACE))
        missing_buttons.addWidget(self.use_for_replace_btn)
        self.use_for_remove_btn = QPushButton(_("Remove This Path"))
        self.use_for_remove_btn.clicked.connect(lambda: self._use_missing_path(path_replace.MODE_REMOVE))
        missing_buttons.addWidget(self.use_for_remove_btn)
        missing_buttons.addStretch()
        missing_layout.addLayout(missing_buttons)
        self.missing_tree = QTreeWidget()
        self.missing_tree.setHeaderLabels([_("Directory"), _("Status"), _("Config"), _("Mapping"), _("Field")])
        self.missing_tree.itemSelectionChanged.connect(self._update_buttons)
        missing_layout.addWidget(self.missing_tree)
        self.tabs.addTab(missing_tab, _("Missing Directories"))
        layout.addWidget(self.tabs, 1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        bottom = QHBoxLayout()
        self.undo_btn = QPushButton(_("Undo Last Change"))
        self.undo_btn.clicked.connect(self._on_undo)
        bottom.addWidget(self.undo_btn)
        bottom.addStretch()
        self.apply_btn = QPushButton(_("Apply"))
        self.apply_btn.clicked.connect(self._on_apply)
        bottom.addWidget(self.apply_btn)
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

    def _with_browse(self, line_edit: QLineEdit) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(line_edit, 1)
        browse = QPushButton(_("Browse..."))
        browse.clicked.connect(lambda: self._browse_into(line_edit))
        row_layout.addWidget(browse)
        return row

    def _browse_into(self, line_edit: QLineEdit):
        selected = QFileDialog.getExistingDirectory(self, _("Select Directory"), line_edit.text().strip())
        if selected:
            line_edit.setText(selected)

    # ----- state -----

    def _mode(self) -> str:
        return path_replace.MODE_REPLACE if self.replace_radio.isChecked() else path_replace.MODE_REMOVE

    def _on_mode_changed(self, *_args):
        self.new_path_row.setEnabled(self._mode() == path_replace.MODE_REPLACE)
        self._set_plan(None)

    def _checked_hit_ids(self) -> list:
        ids = []
        for i in range(self.hits_tree.topLevelItemCount()):
            item = self.hits_tree.topLevelItem(i)
            hit_id = item.data(0, _HIT_ID_ROLE)
            if hit_id and item.checkState(0) == Qt.CheckState.Checked:
                ids.append(hit_id)
        return ids

    def _update_buttons(self):
        self.apply_btn.setEnabled(self._plan is not None and bool(self._checked_hit_ids()))
        self.undo_btn.setEnabled(path_replace.can_undo())
        has_missing = bool(self._selected_missing_path())
        self.use_for_replace_btn.setEnabled(has_missing)
        self.use_for_remove_btn.setEnabled(has_missing)

    def _set_plan(self, plan):
        self._plan = plan
        self.hits_tree.blockSignals(True)
        self.hits_tree.clear()
        if plan is not None:
            for hit in plan.hits:
                item = QTreeWidgetItem([
                    hit.config, hit.action_type, hit.mapping_name, hit.field, hit.old_value,
                    hit.new_value if hit.kind == path_replace.HIT_REPLACE
                    else _("(removed)") if hit.kind == path_replace.HIT_REMOVE else "",
                    self._hit_note(hit),
                ])
                if hit.applicable:
                    item.setData(0, _HIT_ID_ROLE, hit.hit_id)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.CheckState.Checked)
                self.hits_tree.addTopLevelItem(item)
            for column in range(self.hits_tree.columnCount()):
                self.hits_tree.resizeColumnToContents(column)
        self.hits_tree.blockSignals(False)
        self._update_buttons()

    @staticmethod
    def _hit_note(hit) -> str:
        if hit.kind == path_replace.HIT_MANUAL:
            prefix = _("Manual: ")
        elif hit.kind == path_replace.HIT_NOTE:
            prefix = _("Note: ")
        else:
            prefix = ""
        return prefix + localized_str(hit.message) if hit.message else prefix.strip()

    # ----- actions -----

    def _on_search(self):
        mode = self._mode()
        new_path = self.new_path_edit.text().strip() if mode == path_replace.MODE_REPLACE else None
        try:
            plan = path_replace.plan_path_change(mode, self.old_path_edit.text().strip(), new_path)
        except (ValueError, path_replace.MissingDependencyError) as exc:
            QMessageBox.warning(self, _("Replace Paths"), localized_str(exc.args[0] if exc.args else exc))
            return
        self._set_plan(plan)
        self.tabs.setCurrentWidget(self.hits_tree)
        applicable = sum(1 for hit in plan.hits if hit.applicable)
        files = len({hit.config for hit in plan.hits if hit.applicable})
        text = _("{0} hit(s), {1} applicable, in {2} config file(s).").format(len(plan.hits), applicable, files)
        if plan.errors:
            text += " " + _("Unreadable configs: {0}").format(
                "; ".join(f"{config}: {localized_str(error)}" for config, error in plan.errors)
            )
        self.status_label.setText(text)

    def _on_apply(self):
        if self._plan is None:
            return
        if self._is_run_active():
            QMessageBox.warning(
                self, _("Replace Paths"),
                _("A batch run is in progress. Apply the change once it has finished."),
            )
            return
        hit_ids = self._checked_hit_ids()
        files = len({hit_id.rsplit("#", 1)[0] for hit_id in hit_ids})
        answer = QMessageBox.question(
            self, _("Replace Paths"),
            _("Change {0} value(s) in {1} config file(s)? Each file is backed up first.").format(len(hit_ids), files),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = path_replace.apply_path_change(self._plan, hit_ids, skip_configs=set(self._unsaved_configs()))
        except path_replace.MissingDependencyError as exc:
            QMessageBox.critical(self, _("Replace Paths"), localized_str(exc.args[0]))
            return
        self._set_plan(None)
        self.status_label.setText(_("{0} value(s) changed in {1} config file(s).").format(
            result.changed_values, len(result.written)
        ))
        lines = [self.status_label.text()]
        if result.reformatted:
            lines.append(_("Rewritten with normalized indentation: {0}").format(", ".join(result.reformatted)))
        for config, reason in result.skipped:
            lines.append(_("Not changed: {0}: {1}").format(config, localized_str(reason)))
        for config, problem in result.warnings:
            lines.append(_("Check: {0}: {1}").format(config, localized_str(problem)))
        if len(lines) > 1:
            QMessageBox.information(self, _("Replace Paths"), "\n".join(lines))
        if self._on_applied is not None:
            self._on_applied(result.written)

    def _on_undo(self):
        if self._is_run_active():
            QMessageBox.warning(
                self, _("Replace Paths"),
                _("A batch run is in progress. Undo the change once it has finished."),
            )
            return
        answer = QMessageBox.question(
            self, _("Replace Paths"), _("Restore the config files changed by the last path change?")
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        restored, skipped = path_replace.undo_last_change()
        self._set_plan(None)
        lines = [_("{0} config file(s) restored.").format(len(restored))]
        for path, reason in skipped:
            lines.append(_("Not restored: {0}: {1}").format(path, localized_str(reason)))
        self.status_label.setText(lines[0])
        QMessageBox.information(self, _("Replace Paths"), "\n".join(lines))
        if self._on_applied is not None:
            self._on_applied(restored)

    def _on_find_missing(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            missing, errors = path_replace.find_missing_directories()
        except path_replace.MissingDependencyError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, _("Replace Paths"), localized_str(exc.args[0]))
            return
        QApplication.restoreOverrideCursor()
        self.missing_tree.clear()
        for entry in missing:
            status = _("not reachable") if entry.status == "unreachable" else _("missing")
            parent = QTreeWidgetItem([entry.path, status, "", "", ""])
            parent.setData(0, _MISSING_PATH_ROLE, entry.path)
            parent.setText(2, _("{0} reference(s)").format(len(entry.references)))
            for ref in entry.references:
                child = QTreeWidgetItem(["", "", ref["config"], ref["mapping"], ref["field"]])
                child.setData(0, _MISSING_PATH_ROLE, entry.path)
                parent.addChild(child)
            self.missing_tree.addTopLevelItem(parent)
        self.missing_tree.resizeColumnToContents(0)
        text = _("{0} missing directory(s) found.").format(len(missing))
        if errors:
            text += " " + _("Unreadable configs: {0}").format(
                "; ".join(f"{config}: {localized_str(error)}" for config, error in errors)
            )
        self.status_label.setText(text)
        self._update_buttons()

    def _selected_missing_path(self) -> Optional[str]:
        items = self.missing_tree.selectedItems()
        return items[0].data(0, _MISSING_PATH_ROLE) if items else None

    def _use_missing_path(self, mode: str):
        path = self._selected_missing_path()
        if not path:
            return
        self.old_path_edit.setText(path)
        if mode == path_replace.MODE_REPLACE:
            self.replace_radio.setChecked(True)
            self.new_path_edit.setFocus()
            self.tabs.setCurrentWidget(self.hits_tree)
        else:
            self.remove_radio.setChecked(True)
            self._on_search()
