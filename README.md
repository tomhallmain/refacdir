# refacdir
This is a small collection of scripts for file management scripting.

Modify the config_example.yaml file to set a configuration to perform various file management actions.

Available batch actions include:
- Duplicate removal
- File renaming, including the following functions:
  - `move_files`
  - `rename_by_ctime`
  - `rename_by_mtime`
- Directory flattening - take all files in recursive directories and flatten them into the base directory
- Backups, with the following modes:
  - `PUSH_AND_REMOVE`
  - `PUSH`
  - `PUSH_DUPLICATES`
  - `MIRROR`
  - `MIRROR_DUPLICATES`
- Observe directory state by counts of file types

Define custom named functions and sets of file types in the config YAML `filename_mapping_functions` and `filetype_definitions` headers to be referenced in the other parts of the config. Similarly, define custom functions in `custom_file_name_search_funcs.py` and add the function name refs to the config YAML to add custom search logic for gathering files to rename or move.

Once all configurations are defined, run `run.py` to perform the actions. The actions will be run in the order they are listed in the config file. Each configuration file will create a batch job which will run in sequence sorted by the name of the config file.

