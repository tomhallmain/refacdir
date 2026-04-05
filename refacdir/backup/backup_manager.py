from refacdir.utils.logger import setup_logger
from refacdir.utils.translations import I18N

# Set up logger for backup manager
logger = setup_logger('backup_manager')
_ = I18N._


class BackupManager:
    def __init__(
        self,
        name="BackupManager",
        mappings=None,
        test=True,
        overwrite=False,
        warn_duplicates=False,
        skip_confirm=False,
        app_actions=None,
        progress_start=0.0,
        progress_end=1.0,
    ):
        if mappings is None:
            mappings = []
        self.name = name
        self.backup_mappings = mappings
        self.test = test
        self.overwrite = overwrite
        self.warn_duplicates = warn_duplicates
        self.skip_confirm = skip_confirm
        self.app_actions = app_actions
        self.progress_start = progress_start
        self.progress_end = progress_end

    def set_test(self, test):
        self.test = test

    def clean(self):
        for mapping in self.backup_mappings:
            if mapping.will_run:
                mapping.clean()

    def run(self):
        self.run_backups()

    def _job_progress(self, job_fraction: float):
        """Map 0–1 within this backup job to the batch progress bar span."""
        job_fraction = max(0.0, min(1.0, job_fraction))
        if self.app_actions:
            g = self.progress_start + (self.progress_end - self.progress_start) * job_fraction
            self.app_actions.progress_bar_update(None, g)

    def _mapping_job_fraction(self, mapping_index: int, total_mappings: int, local_progress: float) -> float:
        """local_progress is 0–1 for this mapping (scan + sync)."""
        return (mapping_index + max(0.0, min(1.0, local_progress))) / max(1, total_mappings)

    def run_backups(self):
        logger.info("TESTING BACKUPS" if self.test else "RUNNING BACKUPS")
        logger.info("The following backups will be run:")
        for mapping in self.backup_mappings:
            if mapping.will_run:
                logger.info(str(mapping))

        runnable = [m for m in self.backup_mappings if m.will_run]
        m = len(runnable)
        if m == 0:
            self._job_progress(1.0)
            return

        if not self.skip_confirm:
            self.confirm_backups()

        for i, mapping in enumerate(runnable):

            def setup_progress(p: float, msg: str, _i=i, _m=mapping):
                self._job_progress(self._mapping_job_fraction(_i, m, 0.0 + 0.5 * p))
                if self.app_actions:
                    self.app_actions.progress_text(
                        _('Backup "{0}" ({1}/{2}): {3}').format(_m.name, _i + 1, m, msg)
                    )

            logger.info(
                "Starting backup mapping %s (%s/%s): %s -> %s",
                mapping.name,
                i + 1,
                m,
                mapping.source_dir,
                mapping.target_dir,
            )
            mapping.setup(self.overwrite, self.warn_duplicates, progress=setup_progress if self.app_actions else None)

            def backup_progress(p: float, msg: str, _i=i, _m=mapping):
                self._job_progress(self._mapping_job_fraction(_i, m, 0.5 + 0.45 * p))
                if self.app_actions:
                    self.app_actions.progress_text(
                        _('Backup "{0}" ({1}/{2}): {3}').format(_m.name, _i + 1, m, msg)
                    )

            logger.info(
                "Running backup phase for mapping %s (%s/%s) (test=%s)",
                mapping.name,
                i + 1,
                m,
                self.test,
            )
            mapping.backup(test=self.test, progress=backup_progress if self.app_actions else None)

            self._job_progress(self._mapping_job_fraction(i, m, 1.0))
            mapping.report_failures()

    def confirm_backups(self):
        confirm = input("\nCONFIRM BACKUP (y/n): ")
        if not confirm.lower() == "y":
            logger.info("No change made.")
            exit()
        confirm = input("\nCONFIRM BACKUP AGAIN (y/n): ")
        if not confirm.lower() == "y":
            logger.info("No change made.")
            exit()
        logger.info("\nConfirmations received, running full backups.")
