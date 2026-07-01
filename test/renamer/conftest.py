"""
Renamer test conventions.

Shared registry/config fixtures: ``restore_batch_configs``, ``restore_batch_registries``,
``restore_filename_mapping_registry`` (root ``test/conftest.py``).

Reserve ``FileRenamer(test=True)`` / ``BatchRenamer(test=True)`` / YAML ``test: true``
only for assertions about *user* dry-run behavior (no ``os.rename``). For other tests,
use ``test=False`` (the default) so the flag is not confused with pytest.
"""
