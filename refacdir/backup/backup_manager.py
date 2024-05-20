

class BackupManager:
    def __init__(self, name="BackupManager", mappings=[], test=True, overwrite=False, warn_duplicates=False, skip_confirm=False):
        self.name = name
        self.backup_mappings = mappings
        self.test = test
        self.overwrite = overwrite
        self.warn_duplicates = warn_duplicates
        self.skip_confirm = skip_confirm

    def set_test(self, test):
        self.test = test

    def clean(self):
        for mapping in self.backup_mappings:
            if mapping.will_run:
                mapping.clean()

    def run_backup(self):
        print("TESTING BACKUPS" if self.test else "RUNNING BACKUPS")
        print("The following backups will be run:")
        for mapping in self.backup_mappings:
            if mapping.will_run:
                print(str(mapping))
        if not self.skip_confirm:
            self.confirm_backups()
        for mapping in self.backup_mappings:
            if mapping.will_run:
                mapping.setup(self.overwrite, self.warn_duplicates)
                mapping.backup(test=self.test)
        for mapping in self.backup_mappings:
            if mapping.will_run:
                mapping.report_failures()

    def confirm_backups(self):
        confirm = input("\nCONFIRM BACKUP (y/n): ")
        if not confirm.lower() == "y":
            print("No change made.")
            exit()
        confirm = input("\nCONFIRM BACKUP AGAIN (y/n): ")
        if not confirm.lower() == "y":
            print("No change made.")
            exit()
        print("\nConfirmations received, running full backups.")
