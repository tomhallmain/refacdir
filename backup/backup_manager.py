

class BackupManager:
    def __init__(self, mappings=[], test=True, overwrite=False, warn_duplicates=False):
        self.backup_mappings = mappings
        self.test = test
        self.overwrite = overwrite
        self.warn_duplicates = warn_duplicates

    def set_test(self, test):
        self.test = test

    def clean(self):
        for mapping in self.backup_mappings:
            if mapping.will_run:
                mapping.clean()

    def run_backup(self):
        print("TESTING" if self.test else "RUNNING BACKUPS")
        for mapping in self.backup_mappings:
            if mapping.will_run:
                mapping.setup(self.overwrite, self.warn_duplicates)
                mapping.backup(test=self.test)
        for mapping in self.backup_mappings:
            if mapping.will_run:
                mapping.report_failures()

    def confirm_backups(self):
        print("The following backups will be run:")
        for mapping in self.backup_mappings:
            if mapping.will_run:
                print(str(mapping))
        confirm = input("\nCONFIRM BACKUP (y/n): ")
        if not confirm.lower() == "y":
            print("No change made.")
            exit()
        confirm = input("\nCONFIRM BACKUP AGAIN (y/n): ")
        if not confirm.lower() == "y":
            print("No change made.")
            exit()
        print("\nConfirmations received, running full backups.")
