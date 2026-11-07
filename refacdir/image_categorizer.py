import os
import sys

from refacdir.config import config
from refacdir.utils.confirm import confirm_action
from refacdir.utils.translations import LocalizedText, _
from refacdir.utils.utils import Utils
from refacdir.utils.logger import setup_logger

# Set up logger for image categorizer
logger = setup_logger('image_categorizer')

weidr_imported = False

if config.weidr_loc is not None:
    try:
        # Weidr keeps its first-party packages under src/ and imports them
        # unprefixed internally (``from compare.base_compare import ...``), so
        # src/ is the entry that goes on the path. Appended, not prepended:
        # Weidr's src/ui would otherwise shadow this project's own top-level
        # ui package, which app_qt.py imports after this module is loaded.
        sys.path.append(os.path.join(config.weidr_loc, "src"))
        from compare.compare_embeddings_clip import CompareEmbeddingClip
        weidr_imported = True
    except Exception as e:
        logger.error(f"Failed to import Weidr: {e}")


class ImageCategorizer:
    '''
    Categorize images into directories based on their CLIP signatures.
    '''
    def __init__(self, name="Image Categorizer", test=False, skip_confirm=False, source_dir=".", exclude_dirs=[],
                 file_types=[".png", ".jpg", ".jpeg"], categories=["art", "photograph"],
                 recursive=True, app_actions=None):
        self.name = name
        self.test = test
        self.skip_confirm = skip_confirm
        self.app_actions = app_actions
        self.source_dir = source_dir
        self.file_types = file_types
        self.categories = categories
        self.recursive = recursive
        self.exclude_dirs = []
        self.segregation_map = {}

        if not weidr_imported:
            raise Exception(LocalizedText("Invalid ImageCategorizer config - Weidr not imported"))

        if not Utils.isdir_with_retry(source_dir):
            raise Exception(LocalizedText("Source directory {0} is invalid", source_dir))
        
        logger.info("Excluding directories from image categorization:")
        for d in exclude_dirs:
            if os.path.abspath(d) == d:
                full_path = d
            else:
                full_path = os.path.join(os.path.abspath(self.source_dir), d)
            if not Utils.isdir_with_retry(full_path):
                raise Exception(LocalizedText("Invalid exclude directory: {0}", d))
            logger.info(full_path)
            self.exclude_dirs.append(full_path)

        if len(categories) == 0:
            raise Exception(LocalizedText("No categories provided"))
        
        # Each category's own output folder is excluded from the scan so a second
        # run does not re-categorize files an earlier run already sorted. These
        # are not validated for existence: run() creates them.
        for category in categories:
            full_path = os.path.join(os.path.abspath(self.source_dir), category)
            self.exclude_dirs.append(full_path)
            self.segregation_map[category] = []

    def run(self):
        for f in self._get_files():
            temp_dict = {category: category for category in self.categories}
            similarities = CompareEmbeddingClip.single_text_compare(f, temp_dict)
            max_similarity = max(similarities.values())
            for category, similarity in similarities.items():
                if similarity == max_similarity:
                    # One category per file: on a tie the first match wins, so the
                    # file is never queued for two destinations and moved twice.
                    self.segregation_map[category].append(f)
                    break

        planned = [(category, f) for category, files in self.segregation_map.items() for f in files]
        if len(planned) == 0:
            logger.warning(_("{0}: no images found to categorize under {1}").format(self.name, self.source_dir))
            return

        if self.test:
            logger.info(
                "|=============== " + _("TEST (dry run) {0}: no files moved").format(self.name) + " ===============|"
            )
            logger.info(_("TEST {0}: would categorize {1} image(s)").format(self.name, len(planned)))
            for category, f in planned:
                logger.info(_("TEST move {0} -> {1}").format(f, self._category_path(category, f)))
            return

        logger.info(_("{0}: categorizing {1} image(s) under {2}").format(self.name, len(planned), self.source_dir))
        if not self.skip_confirm and not confirm_action(
            self.app_actions,
            _("Confirm image categorization"),
            _('"{0}": move {1} image(s) under {2} into categories {3}?').format(
                self.name, len(planned), self.source_dir, ", ".join(self.categories)
            ),
        ):
            logger.info(_("Operation cancelled by user"))
            return

        for category in self.categories:
            os.makedirs(os.path.join(self.source_dir, category), exist_ok=True)

        for category, f in planned:
            new_path = self._category_path(category, f)
            if os.path.exists(new_path):
                logger.warning(_("File already exists: {0}").format(new_path))
                continue
            Utils.move(f, new_path)
            logger.info(_("moved {0} -> {1}").format(f, new_path))

    def _category_path(self, category, file_path):
        return os.path.join(self.source_dir, category, os.path.basename(file_path))

    def _get_files(self):
        for root, dirs, files in os.walk(self.source_dir):
            if self._is_excluded(root):
                dirs[:] = []
                continue
            if not self.recursive:
                dirs[:] = []
            for f in files:
                if any(f.endswith(ext) for ext in self.file_types):
                    yield os.path.join(root, f)

    def _is_excluded(self, dir_path):
        """True when dir_path is an excluded directory or sits inside one."""
        dir_path = os.path.normcase(os.path.abspath(dir_path))
        for excluded in self.exclude_dirs:
            excluded = os.path.normcase(os.path.abspath(excluded))
            if dir_path == excluded or dir_path.startswith(excluded + os.sep):
                return True
        return False
