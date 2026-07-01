"""Window for viewing batch job history and reversing renames/moves."""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
)

from refacdir.batch_job_history import (
    MAX_BATCH_JOB_HISTORY,
    find_batch_job,
    get_batch_job_history,
    job_mapping_groups,
    reverse_job,
)
from refacdir.lib.multi_display import SmartWindow
from refacdir.utils.translations import I18N

_ = I18N._


def _format_job_summary(job: dict) -> str:
    started = job.get("started_at", "")
    try:
        dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        started = dt.strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        pass
    configs = ", ".join(job.get("configs") or []) or _("(none)")
    op_count = len(job.get("operations") or [])
    rev_count = job.get("reversible_operation_count", 0)
    cancelled = _(" (cancelled)") if job.get("cancelled") else ""
    return f"{started}{cancelled} — {configs} — {op_count} op(s), {rev_count} reversible"


def _format_mapping_label(group: dict) -> str:
    config = group.get("config") or _("(unknown config)")
    name = group.get("mapping_name") or _("(untagged)")
    op_count = group.get("operation_count", 0)
    rev_count = group.get("reversible_count", 0)
    return f"{config} / {name} — {op_count} op(s), {rev_count} reversible"


def _format_job_detail(job: dict, *, mapping_filter: tuple[str, str] | None = None) -> str:
    lines = [
        f"Job ID: {job.get('job_id', '')}",
        f"Started: {job.get('started_at', '')}",
        f"Finished: {job.get('finished_at', '')}",
        f"Configs: {', '.join(job.get('configs') or [])}",
        f"Cancelled: {job.get('cancelled', False)}",
        "",
        "Action counts:",
    ]
    for action, count in (job.get("action_counts") or {}).items():
        if count:
            lines.append(f"  {action}: {count}")
    failures = job.get("failures") or []
    if failures:
        lines.extend(["", "Failures:"])
        lines.extend(f"  - {f}" for f in failures)

    filter_label = _("(all mappings)")
    if mapping_filter is not None:
        config, mapping_name = mapping_filter
        config_label = config or _("(unknown config)")
        mapping_label = mapping_name or _("(untagged)")
        filter_label = f"{config_label} / {mapping_label}"
    lines.extend(["", f"File operations — {filter_label}:"])

    for i, op in enumerate(job.get("operations") or [], 1):
        meta = op.get("meta") or {}
        op_config = meta.get("config") or ""
        op_mapping = meta.get("mapping_name") or ""
        if mapping_filter is not None:
            config, mapping_name = mapping_filter
            if op_config != config or op_mapping != mapping_name:
                continue

        mapping_label = op_mapping or _("(untagged)")

        status = ""
        if op.get("reversed"):
            status = " [reversed]"
        elif op.get("reversible"):
            dest = op.get("dest", "")
            if dest and os.path.isfile(dest):
                status = " [can reverse]"
            else:
                status = " [missing at dest]"
        elif not op.get("reversible"):
            status = " [not reversible]"
        lines.append(
            f"  {i}. [{op_config} / {mapping_label}] {op.get('type', '?')}: "
            f"{op.get('source', '')} -> {op.get('dest', '')}{status}"
        )
    return "\n".join(lines)


class BatchHistoryWindow(SmartWindow):
    """Show recent batch jobs and reverse rename/move operations."""

    def __init__(self, parent=None):
        super().__init__(
            persistent_parent=parent,
            position_parent=parent,
            title=_("Batch Job History"),
            geometry="1100x560",
            window_flags=Qt.WindowType.Window,
        )
        self._selected_job_id: str | None = None
        self._selected_mapping: tuple[str, str] | None = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel(
            _(
                "Last {0} batch jobs (stored in encrypted cache). "
                "Reverse an entire job or a single renamer mapping."
            ).format(MAX_BATCH_JOB_HISTORY)
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        self.job_list = QListWidget()
        self.job_list.currentItemChanged.connect(self._on_job_selected)
        splitter.addWidget(self.job_list)

        self.mapping_list = QListWidget()
        self.mapping_list.currentItemChanged.connect(self._on_mapping_selected)
        splitter.addWidget(self.mapping_list)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Consolas", 10))
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 3)
        layout.addWidget(splitter)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton(_("Refresh"))
        self.refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(self.refresh_btn)

        self.preview_mapping_btn = QPushButton(_("Preview reverse mapping"))
        self.preview_mapping_btn.clicked.connect(lambda: self._reverse_selected(dry_run=True, mapping_only=True))
        btn_row.addWidget(self.preview_mapping_btn)

        self.reverse_mapping_btn = QPushButton(_("Reverse mapping"))
        self.reverse_mapping_btn.clicked.connect(lambda: self._reverse_selected(dry_run=False, mapping_only=True))
        btn_row.addWidget(self.reverse_mapping_btn)

        self.preview_btn = QPushButton(_("Preview reverse job"))
        self.preview_btn.clicked.connect(lambda: self._reverse_selected(dry_run=True, mapping_only=False))
        btn_row.addWidget(self.preview_btn)

        self.reverse_btn = QPushButton(_("Reverse entire job"))
        self.reverse_btn.clicked.connect(lambda: self._reverse_selected(dry_run=False, mapping_only=False))
        btn_row.addWidget(self.reverse_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)
        self._update_mapping_buttons()

    def _update_mapping_buttons(self):
        enabled = self._selected_mapping is not None
        self.preview_mapping_btn.setEnabled(enabled)
        self.reverse_mapping_btn.setEnabled(enabled)

    def refresh(self):
        job_id = self._selected_job_id
        self.job_list.clear()
        history = get_batch_job_history()
        if not history:
            self.mapping_list.clear()
            self.detail.setPlainText(_("No batch jobs recorded yet. Run operations (non test mode) to build history."))
            self._selected_job_id = None
            self._selected_mapping = None
            self._update_mapping_buttons()
            return

        restore_row = 0
        for row, job in enumerate(history):
            item = QListWidgetItem(_format_job_summary(job))
            item.setData(Qt.UserRole, job.get("job_id"))
            self.job_list.addItem(item)
            if job.get("job_id") == job_id:
                restore_row = row

        self.job_list.setCurrentRow(restore_row)

    def _selected_job_id_from_list(self) -> str | None:
        item = self.job_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _selected_mapping_from_list(self) -> tuple[str, str] | None:
        item = self.mapping_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _refresh_mapping_list(self, job: dict | None):
        self.mapping_list.clear()
        if job is None:
            self._selected_mapping = None
            self._update_mapping_buttons()
            return

        groups = job_mapping_groups(job)
        if not groups:
            self._selected_mapping = None
            self._update_mapping_buttons()
            return

        prev = self._selected_mapping
        restore_row = None
        for row, group in enumerate(groups):
            item = QListWidgetItem(_format_mapping_label(group))
            key = (group.get("config") or "", group.get("mapping_name") or "")
            item.setData(Qt.UserRole, key)
            self.mapping_list.addItem(item)
            if key == prev:
                restore_row = row

        if restore_row is not None:
            self.mapping_list.setCurrentRow(restore_row)
        else:
            self.mapping_list.clearSelection()
            self._selected_mapping = None
            self._update_mapping_buttons()

    def _on_job_selected(self, current: QListWidgetItem | None, _previous=None):
        if current is None:
            self._selected_job_id = None
            self._refresh_mapping_list(None)
            self.detail.clear()
            return

        self._selected_job_id = current.data(Qt.UserRole)
        if _previous is not None and _previous.data(Qt.UserRole) != self._selected_job_id:
            self._selected_mapping = None
        job = find_batch_job(self._selected_job_id)
        self._refresh_mapping_list(job)
        self._refresh_detail()

    def _on_mapping_selected(self, current: QListWidgetItem | None, _previous=None):
        self._selected_mapping = self._selected_mapping_from_list() if current else None
        self._update_mapping_buttons()
        self._refresh_detail()

    def _refresh_detail(self):
        job_id = self._selected_job_id
        if not job_id:
            self.detail.clear()
            return
        job = find_batch_job(job_id)
        if not job:
            self.detail.setPlainText(_("Job not found (history may have changed)."))
            return

        if self._selected_mapping is not None:
            self.detail.setPlainText(_format_job_detail(job, mapping_filter=self._selected_mapping))
        else:
            self.detail.setPlainText(_format_job_detail(job))

    def _reverse_selected(self, *, dry_run: bool, mapping_only: bool):
        job_id = self._selected_job_id_from_list()
        if not job_id:
            QMessageBox.information(self, _("Batch history"), _("Select a job first."))
            return

        config = None
        mapping_name = None
        if mapping_only:
            if not self._selected_mapping:
                QMessageBox.information(self, _("Batch history"), _("Select a renamer mapping first."))
                return
            config, mapping_name = self._selected_mapping
            if not mapping_name and not config:
                QMessageBox.information(
                    self,
                    _("Batch history"),
                    _("This job has no mapping tags; use Reverse entire job instead."),
                )
                return

        if not dry_run:
            if mapping_only:
                prompt = _(
                    "Move files back for mapping \"{0}\" in config \"{1}\"?\n"
                    "Only operations from this mapping are reversed (newest first). "
                    "If a later mapping renamed the same file, reverse that mapping first."
                ).format(mapping_name, config)
                title = _("Reverse mapping")
            else:
                prompt = _(
                    "Move files back along all recorded rename/move paths for this job?\n"
                    "Operations are applied newest-first. Files must still exist at their destination."
                )
                title = _("Reverse entire job")
            answer = QMessageBox.question(
                self,
                title,
                prompt,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        try:
            result = reverse_job(job_id, config=config, mapping_name=mapping_name, dry_run=dry_run)
        except ValueError as exc:
            QMessageBox.warning(self, _("Batch history"), str(exc))
            return

        if mapping_only:
            title = _("Preview reverse mapping") if dry_run else _("Reverse mapping")
        else:
            title = _("Preview reverse job") if dry_run else _("Reverse entire job")
        msg = _(
            "Attempted: {0}\nSucceeded: {1}\nFailed: {2}\nSkipped (not reversible or missing): {3}"
        ).format(result.attempted, result.succeeded, result.failed, result.skipped)
        if result.errors:
            msg += "\n\n" + "\n".join(result.errors[:20])
            if len(result.errors) > 20:
                msg += f"\n... and {len(result.errors) - 20} more"
        QMessageBox.information(self, title, msg)
        self.refresh()
