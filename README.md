# refacdir
This is a small collection of scripts for file management scripting.

Copy `examples/config_example.yaml` into your user configs directory under a new name and edit it to set up file management actions.

User configs, caches and logs live outside the repo, in a per-user app data directory:

- Windows: `%LOCALAPPDATA%\refacdir\` (`configs\`, `cache\`, `logs\`)
- Linux/macOS: `~/.local/share/refacdir/` (`configs/`, `cache/`, `logs/`)

Configs and cache files left in the repo by older versions are moved there automatically on first start.

Available batch actions include:
- Duplicate removal
- File renaming, including the following functions:
  - `move_files`
  - `rename_by_ctime`
  - `rename_by_mtime`
- Directory flattening - take all files in recursive directories and flatten them into the base directory
- Archive extraction - unpack ZIP files matching a name pattern and merge their contents into one directory
- Backups, with the following modes:
  - `PUSH_AND_REMOVE`
  - `PUSH`
  - `PUSH_DUPLICATES`
  - `MIRROR`
  - `MIRROR_DUPLICATES`
  - `FILES_AND_DIRS` or `DIRS_ONLY` (both exclusive of the other modes)
- Observe directory state by counts of file types
- Image categorization using CLIP (requires [Weidr](https://github.com/tomhallmain/Weidr))

Define custom named functions and sets of file types in the config YAML `filename_mapping_functions` and `filetype_definitions` headers to be referenced in the other parts of the config. Similarly, define your own Python search functions in `custom_file_name_search_funcs.py` in your user configs directory (created from a template on first use; edits apply on the next run) and reference them by name in the config YAML to add custom search logic for gathering files to rename or move.

For the built-in `REP`/`DIGITS`/`HEX`/`ALNUM` pattern primitives, you don't need to declare a named `filename_mapping_functions` entry for every value — an inline `{{type:arg1:arg2}}` form works directly in a pattern, e.g. `{{digits:4}}` (four digits), `{{hex:64}}` (64 uppercase hex chars), or `{{alnum:8:true:_}}` (8 lowercase alphanumeric chars plus underscore). This is purely additive: existing named `filename_mapping_functions` declarations keep working unchanged.

Once all configurations are defined, run `run.py` to perform the actions. The actions will be run in the order they are listed in the config file. Each configuration file will create a batch job which will run in sequence sorted by the name of the config file.

# UI

Start the UI by running `app_qt.py`.

The UI exits automatically after a period without keyboard or mouse activity (default 30 minutes; configurable under Operation Settings).

# Server

Set configuration options in `config.json` in your user configs directory (copy from `examples/config_example.json`) for a server port to make use of the server while the UI is running. Calls to the server made with Python's multiprocessing client will update the UI as specified, but leave anything unspecified as already set in the UI. This can be helpful to use in conjunction with other applications that involve images. For an example, see [this class](https://github.com/tomhallmain/Weidr/blob/master/extensions/refacdir_client.py).



# Build

`python build_exe.py` builds the UI into a single executable with [Nuitka](https://nuitka.net): `dist/RefacDir.exe` on Windows, `dist/RefacDir` on macOS and Linux. Build on each operating system you want an executable for; Nuitka does not cross-compile.

Prerequisites:

- Python with `venv` and `pip`. The script creates `.venv-build` from `requirements-build.txt` so nothing else in your environment is bundled; `--current-env` builds with the running interpreter instead.
- A C compiler: Visual Studio Build Tools on Windows (or let Nuitka download MinGW), Xcode Command Line Tools on macOS, `gcc` on Linux.

The build checks itself with `RefacDir --smoke-test` before finishing. Extra arguments are passed to Nuitka, e.g. `python build_exe.py --jobs=4`.

`python build_exe.py --headless` builds `dist/RefacDirHeadless(.exe)` instead: the MCP server with no window (`app_headless.py`), with the `mcp` package included.

`--with-oqs` (for either build) adds quantum-safe key encapsulation from [liboqs](https://github.com/open-quantum-safe/liboqs-python): the build installs liboqs-python and bundles the liboqs library it loads. If liboqs is not installed yet, liboqs-python builds it on first import, which needs git, CMake and a C compiler; or set `OQS_INSTALL_PATH` to an existing install. A build without OQS cannot read a settings cache that was encrypted with OQS keys (one written by a source checkout that has liboqs): it starts with empty settings and leaves the cache file untouched. Build with `--with-oqs` if your existing cache uses OQS keys.

What the executable includes and leaves out:

- The test suite and pytest are included, so the Run tests window works.
- Not included: the MCP server in the UI build (use the headless build), liboqs unless built `--with-oqs`, and image categorization (it needs Weidr and its models). 7-Zip stays an external program.
- User data is not stored next to the executable. Configs, caches and logs live in `%LOCALAPPDATA%\refacdir\` on Windows and `~/.local/share/refacdir/` elsewhere, shared with a source checkout on the same machine and account.
- The first start unpacks the executable to a folder under your user cache directory (`refacdir\unpacked\refacdir-<build time>`; on Windows that is inside `%LOCALAPPDATA%\refacdir\`). Folders left by older builds can be deleted.
- Started from a terminal on Windows, the executable prints its log there, but the terminal does not wait for it: the prompt is drawn at launch, so after you close the app the terminal looks stuck until you press Enter. Use `start /wait dist\RefacDir.exe` to make it wait.
