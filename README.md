# refacdir
This is a small collection of scripts for file management scripting.

Copy `examples/config_example.yaml` into your user configs directory under a new name and edit it to set up file management actions.

User configs, caches and logs live outside the repo, in a per-user app data directory:

- Windows: `%LOCALAPPDATA%\refacdir\` (`configs\`, `cache\`, `logs\`)
- Linux/macOS: `~/.local/share/refacdir/` (`configs/`, `cache/`, `logs/`)

Configs and cache files left in the repo by older versions are moved there automatically on first start.

The cache is encrypted. Its keys sit in `MyPersonalApplicationsService/RefacDir__key_store.json` under `%LOCALAPPDATA%` on Windows, `~/Library/Application Support` on macOS and `$XDG_DATA_HOME` (default `~/.local/share`) elsewhere; only the passphrase protecting them stays in the OS keychain. Keys kept in the keychain by older versions are moved into that file on first start. After every write the key store is backed up to an external drive (set `REFACDIR_KEY_BACKUP_DIR` to choose where). Run `python scripts/key_material.py` to check that backup's state, or `python scripts/key_material.py backup` to take one by hand.

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

The build checks itself with `RefacDir --smoke-test` before finishing. Extra arguments are passed to Nuitka, e.g. `python build_exe.py --jobs=4`. Each step is timed and logged to `build/logs/build_exe-<build id>.log`.

`python build_exe.py --with-headless` also builds `dist/RefacDirHeadless(.exe)`: the MCP server with no window (`app_headless.py`). Both executables include the `mcp` package.

Version and reproducibility:

- The version comes from the `VERSION` file at the repo root and shows in the executable's properties, with the build id in its description. The app logs its version and build at startup.
- Each build writes `build/nuitka/build_info.json` (version, build id, OQS, package versions, the commit it was built from), which is bundled, and `build/nuitka/build-requirements.lock.txt`, the build venv's `pip freeze`. `--lock=<file>` installs the build venv from such a file to repeat a build; delete `.venv-build` first for an exact copy.
- Nuitka and PySide6 are pinned in `requirements-build.txt` to a pair known to work.
- Before compressing the executable, the last step of a compile, the build waits until enough memory is free, because running out there loses the whole compile. The plugin that waits ships with [app-release](https://github.com/tomhallmain/release-tools); without app-release installed, the build warns and does not wait. `--min-free-memory=<GiB>` sets the amount; `0` turns the wait off.

Releases are published with `app-release <checkout>`, a separate tool installed with pipx ([release-tools](https://github.com/tomhallmain/release-tools); its README lists the options). It rebuilds any executables in `dist/` that are behind the checkout and publishes them as a GitHub release. Note that `build_info.json`, and so the executable, contains the path of the checkout it was built from.

`--with-oqs` (for either build) adds quantum-safe key encapsulation from [liboqs](https://github.com/open-quantum-safe/liboqs-python): the build installs liboqs-python and bundles the liboqs library it loads. If liboqs is not installed yet, liboqs-python builds it on first import, which needs git, CMake and a C compiler; or set `OQS_INSTALL_PATH` to an existing install. A build without OQS cannot read a settings cache that was encrypted with OQS keys (one written by a source checkout that has liboqs): it starts with empty settings and leaves the cache file untouched. Build with `--with-oqs` if your existing cache uses OQS keys.

What the executable includes and leaves out:

- The test suite and pytest are included, so the Run tests window works.
- Not included: liboqs unless built `--with-oqs`, and image categorization (it needs Weidr and its models). 7-Zip stays an external program.
- User data is not stored next to the executable. Configs, caches and logs live in `%LOCALAPPDATA%\refacdir\` on Windows and `~/.local/share/refacdir/` elsewhere, shared with a source checkout on the same machine and account.
- The first start unpacks the executable to `unpacked/refacdir-<build time>` (`refacdir-headless-<build time>` for the headless build) in the same app data folder. Each executable removes the folders its older builds left there at startup, skipping any a running copy still uses.
- Crashes in native code (Qt, liboqs) leave a Python stack trace in `logs/faults.log` in the app data folder. A build also checks at startup whether the checkout it was built from has changed since, and says so.
- Started from a terminal on Windows, the executable prints its log there, but the terminal does not wait for it: the prompt is drawn at launch, so after you close the app the terminal looks stuck until you press Enter. Use `start /wait dist\RefacDir.exe` to make it wait.
