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
    get_batch_job_history,
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


def _format_job_detail(job: dict) -> str:
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
    lines.extend(["", "File operations:"])
    for i, op in enumerate(job.get("operations") or [], 1):
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
            f"  {i}. {op.get('type', '?')}: {op.get('source', '')} -> {op.get('dest', '')}{status}"
        )
    return "\n".join(lines)


class BatchHistoryWindow(SmartWindow):
    """Show recent batch jobs and reverse rename/move operations."""

    def __init__(self, parent=None):
        super().__init__(
            persistent_parent=parent,
            position_parent=parent,
            title=_("Batch Job History"),
            geometry="900x560",
            window_flags=Qt.WindowType.Window,
        )
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel(
            _("Last {0} batch jobs (stored in encrypted cache). Only renames and moves can be reversed.")
            .format(MAX_BATCH_JOB_HISTORY)
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        self.job_list = QListWidget()
        self.job_list.currentItemChanged.connect(self._on_job_selected)
        splitter.addWidget(self.job_list)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Consolas", 10))
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton(_("Refresh"))
        self.refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(self.refresh_btn)

        self.preview_btn = QPushButton(_("Preview reverse"))
        self.preview_btn.clicked.connect(lambda: self._reverse_selected(dry_run=True))
        btn_row.addWidget(self.preview_btn)

        self.reverse_btn = QPushButton(_("Reverse job"))
        self.reverse_btn.clicked.connect(lambda: self._reverse_selected(dry_run=False))
        btn_row.addWidget(self.reverse_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def refresh(self):
        self.job_list.clear()
        history = get_batch_job_history()
        if not history:
            self.detail.setPlainText(_("No batch jobs recorded yet. Run operations (non test mode) to build history."))
            return
        for job in history:
            item = QListWidgetItem(_format_job_summary(job))
            item.setData(Qt.UserRole, job.get("job_id"))
            self.job_list.addItem(item)
        self.job_list.setCurrentRow(0)

    def _selected_job_id(self) -> str | None:
        item = self.job_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _on_job_selected(self, current: QListWidgetItem | None, _previous=None):
        if current is None:
            self.detail.clear()
            return
        job_id = current.data(Qt.UserRole)
        history = get_batch_job_history()
        job = next((j for j in history if j.get("job_id") == job_id), None)
        if job:
            self.detail.setPlainText(_format_job_detail(job))
        else:
            self.detail.setPlainText(_("Job not found (history may have changed)."))

    def _reverse_selected(self, *, dry_run: bool):
        job_id = self._selected_job_id()
        if not job_id:
            QMessageBox.information(self, _("Batch history"), _("Select a job first."))
            return

        if not dry_run:
            answer = QMessageBox.question(
                self,
                _("Reverse batch job"),
                _(
                    "Move files back along recorded rename/move paths?\n"
                    "Operations are applied newest-first. Files must still exist at their destination."
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        try:
            result = reverse_job(job_id, dry_run=dry_run)
        except ValueError as exc:
            QMessageBox.warning(self, _("Batch history"), str(exc))
            return

        title = _("Preview reverse") if dry_run else _("Reverse job")
        msg = _(
            "Attempted: {0}\nSucceeded: {1}\nFailed: {2}\nSkipped (not reversible or missing): {3}"
        ).format(result.attempted, result.succeeded, result.failed, result.skipped)
        if result.errors:
            msg += "\n\n" + "\n".join(result.errors[:20])
            if len(result.errors) > 20:
                msg += f"\n... and {len(result.errors) - 20} more"
        QMessageBox.information(self, title, msg)
        self.refresh()
        self._on_job_selected(self.job_list.currentItem())
