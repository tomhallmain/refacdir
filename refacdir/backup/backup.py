from refacdir.backup.backup_manager import BackupManager
from refacdir.backup.backup_mapping import BackupMode, BackupMapping

visual_media_file_types = [".png", ".mp4", ".mpg", ".mpeg", ".mov", ".gif", ".jpg", ".jpeg", ".tiff", ".webp", ".webm", ".bmp"]

def main():
    mappings = [
        BackupMapping(
            "C:\\Users\\tehal\\stable-diffusion-webui\\log\\images",
            "D:\\stable-diffusion-webui\\log\\images",
            file_types=visual_media_file_types,
            exclude_dirs=[],
            exclude_removal_dirs=[
                "C:\\Users\\tehal\\stable-diffusion-webui\\log\\images\\arty",
                "C:\\Users\\tehal\\stable-diffusion-webui\\log\\images\\bubble concept",
                "C:\\Users\\tehal\\stable-diffusion-webui\\log\\images\\cute",
                "C:\\Users\\tehal\\stable-diffusion-webui\\log\\images\\Deoldified",
                "C:\\Users\\tehal\\stable-diffusion-webui\\log\\images\\fantasy",
                "C:\\Users\\tehal\\stable-diffusion-webui\\log\\images\\historical",
                "C:\\Users\\tehal\\stable-diffusion-webui\\log\\images\\memes",
                "C:\\Users\\tehal\\stable-diffusion-webui\\log\\images\\naturish",
                "C:\\Users\\tehal\\stable-diffusion-webui\\log\\images\\other",
                "C:\\Users\\tehal\\stable-diffusion-webui\\log\\images\\tests",
            ],
            mode=BackupMode.PUSH_AND_REMOVE,
            will_run=False, # TODO UPDATE
        ),
        BackupMapping(
            "C:\\Users\\tehal\\img",
            "D:\\img",
            file_types=visual_media_file_types,
            exclude_dirs=[],
            exclude_removal_dirs=[
                "C:\\Users\\tehal\\img\\cool",
                "C:\\Users\\tehal\\img\\cute",
                "C:\\Users\\tehal\\img\\manul",
                "C:\\Users\\tehal\\img\\nature",
                "C:\\Users\\tehal\\img\\openposesCollection_v10",
            ],
            mode=BackupMode.PUSH_AND_REMOVE,
            will_run=False,
        ),
    ]

    manager = BackupManager(mappings=mappings, test=True)

    try:
        # manager.run_backup()
        # manager.clean()
        manager.confirm_backups()
        manager.set_test(False)
        manager.run_backup()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
