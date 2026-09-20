import os
import sys

from refacdir.config import config
from refacdir.utils.translations import _
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
                 recursive=True):
        self.name = name
        self.test = test
        self.skip_confirm = skip_confirm
        self.source_dir = source_dir
        self.file_types = file_types
        self.categories = categories
        self.recursive = recursive
        self.exclude_dirs = []
        self.segregation_map = {}

        if not weidr_imported:
            raise Exception("Invalid ImageCategorizer config - Weidr not imported")

        if not Utils.isdir_with_retry(source_dir):
            raise Exception(f"Source directory {source_dir} is invalid")
        
        logger.info("Excluding directories from image categorization:")
        for d in exclude_dirs:
            if os.path.abspath(d) == d:
                full_path = d
            else:
                full_path = os.path.join(os.path.abspath(self.source_dir), d)
            if not Utils.isdir_with_retry(full_path):
                raise Exception("Invalid exclude directory: " + d)
            logger.info(full_path)
            self.exclude_dirs.append(full_path)

        if len(categories) == 0:
            raise Exception("No categories provided")
        
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
            logger.warning(f"{self.name}: no images found to categorize under {self.source_dir}")
            return

        if self.test:
            logger.info(
                f"|=============== TEST (dry run) {self.name}: no files moved ===============|"
            )
            logger.info(f"TEST {self.name}: would categorize {len(planned)} image(s)")
            for category, f in planned:
                logger.info(f"TEST move {f} -> {self._category_path(category, f)}")
            return

        logger.info(f"{self.name}: categorizing {len(planned)} image(s) under {self.source_dir}")
        if not self.skip_confirm:
            confirm = input(
                _("Confirm categorization of {0} image(s) into {1} categories (y/n): ").format(
                    len(planned), len(self.categories)
                )
            )
            if confirm.lower() != "y":
                logger.info("Operation cancelled by user")
                return

        for category in self.categories:
            os.makedirs(os.path.join(self.source_dir, category), exist_ok=True)

        for category, f in planned:
            new_path = self._category_path(category, f)
            if os.path.exists(new_path):
                logger.warning(f"File already exists: {new_path}")
                continue
            Utils.move(f, new_path)
            logger.info(f"moved {f} -> {new_path}")

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
