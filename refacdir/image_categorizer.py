import os
import sys

from refacdir.config import config
from refacdir.utils import Utils

simple_image_compare_imported = False

if config.simple_image_compare_loc is not None:
    try:
        sys.path.insert(0, config.simple_image_compare_loc)
        from compare.compare_embeddings import CompareEmbedding
        simple_image_compare_imported = True
    except Exception as e:
        print(f"Failed to import Simple Image Compare: {e}")


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

        if not simple_image_compare_imported:
            raise Exception("Invalid ImageCategorizer config - Simple image compare not imported")

        if not os.path.isdir(source_dir):
            raise Exception(f"Source directory {source_dir} is invalid")
        
        print("Excluding directories from image categorization:")
        for d in exclude_dirs:
            if os.path.abspath(d) == d:
                full_path = d
            else:
                full_path = os.path.join(os.path.abspath(self.source_dir), d)
            if not os.path.isdir(full_path):
                raise Exception("Invalid exclude directory: " + d)
            print(full_path)
            self.exclude_dirs.append(full_path)

        if len(categories) == 0:
            raise Exception("No categories provided")
        
        for category in categories:
            full_path = os.path.join(os.path.abspath(self.source_dir), d)
            self.exclude_dirs.append(full_path)
            self.segregation_map[category] = []

    def run(self):
        files = self._get_files()

        for f in files:
            temp_dict = {}
            for category in self.categories:
                temp_dict[category] = category
            similarities = CompareEmbedding.single_text_compare(f, temp_dict)
            max_similarity = max(similarities.values())
            for k, v in similarities.items():
                if v == max_similarity:
                    max_category = k
                    self.segregation_map[max_category].append(f)

        for category in self.categories:
            new_dir = os.path.join(self.source_dir, category)
            if not os.path.isdir(new_dir):
                os.mkdir(new_dir)
        
        for category, files in self.segregation_map.items():
            new_dir = os.path.join(self.source_dir, category)
            for f in files:
                new_path = os.path.join(new_dir, os.path.basename(f))
                if not os.path.exists(new_path):
                    Utils.move(f, new_path)
                else:
                    print(f"File already exists: {new_path}")


    def _get_files(self):
        for ext in self.file_types:
            for root, dirs, files in os.walk(self.source_dir):
                if not self.recursive and len(dirs) > 0:
                    continue
                for f in files:
                    if f.endswith(ext) and not self._is_excluded(root):
                        yield os.path.join(root, f)

    def _is_excluded(self, file_path):
        for d in self.exclude_dirs:
            if file_path.startswith(d):
                return True
        return False
