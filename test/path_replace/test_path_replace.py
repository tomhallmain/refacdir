"""``refacdir.path_replace`` against config files in the per-test configs dir."""

import os

import pytest

from refacdir import path_replace
from refacdir.batch import ActionType
from refacdir.config import Config
from test.test_utils import posix_path


@pytest.fixture
def configs_dir():
    return Config.configs_dir()


def write(configs_dir, name, text):
    path = os.path.join(configs_dir, name)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


def read(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


@pytest.fixture
def dirs(tmp_path):
    names = {}
    for key in ("foto", "fotos", "other", "neu"):
        d = tmp_path / key.capitalize()
        d.mkdir()
        names[key] = posix_path(str(d))
    (tmp_path / "Foto" / "inbox").mkdir()
    return names


def renamer_and_dups(d):
    return f"""will_run: true
# A comment that must survive.
actions:
- type: "RENAMER"
  mappings:
  - name: "move"
    function: "move_files"
    locations:
    - "{d['foto']}/inbox"   # inline comment
    mappings:
    - search_patterns: "*{d['foto']}*"
      rename_tag: "{d['foto']}/sorted"

- type: "DUPLICATE_REMOVER"
  mappings:
  - name: "dups"
    source_dirs:
    - "{d['fotos']}"
    exclude_dirs: ["{d['foto']}/keep", "{d['other']}"]
"""


def test_every_action_type_has_path_fields():
    assert set(path_replace.PATH_FIELDS) == set(ActionType)


def test_replace_changes_only_path_fields_and_keeps_the_rest(configs_dir, dirs):
    text = renamer_and_dups(dirs)
    path = write(configs_dir, "a.yaml", text)

    plan = path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"])
    fields = sorted(hit.field for hit in plan.hits)
    assert fields == ["exclude_dirs[0]", "locations[0]", "mappings[0].rename_tag"]
    assert all(hit.kind == path_replace.HIT_REPLACE for hit in plan.hits)

    result = path_replace.apply_path_change(plan)
    assert result.written == ["configs/a.yaml"]
    assert result.reformatted == []
    expected = (
        text.replace(f'"{dirs["foto"]}/inbox"', f'"{dirs["neu"]}/inbox"')
        .replace(f'"{dirs["foto"]}/sorted"', f'"{dirs["neu"]}/sorted"')
        .replace(f'"{dirs["foto"]}/keep"', f'"{dirs["neu"]}/keep"')
    )
    assert read(path) == expected  # comments, the pattern and the sibling dir are untouched


def test_sibling_with_a_common_prefix_is_not_a_hit(configs_dir, dirs):
    write(configs_dir, "a.yaml", renamer_and_dups(dirs))
    plan = path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"])
    assert all(dirs["fotos"] not in hit.old_value for hit in plan.hits)


def test_deselected_hit_is_left_alone(configs_dir, dirs):
    path = write(configs_dir, "a.yaml", renamer_and_dups(dirs))
    plan = path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"])
    keep = next(hit for hit in plan.hits if hit.field == "locations[0]")
    path_replace.apply_path_change(plan, [h.hit_id for h in plan.hits if h is not keep])
    assert f'"{dirs["foto"]}/inbox"' in read(path)
    assert f'"{dirs["neu"]}/sorted"' in read(path)


def test_disabled_config_is_changed_and_master_config_is_not(configs_dir, dirs):
    backup = write(configs_dir, "b.yaml", f"""will_run: false
actions:
- type: "BACKUP"
  mappings:
  - name: "bk"
    backup_mappings:
    - name: "photos"
      source_dir: "{dirs['foto']}"
      target_dir: "{dirs['other']}"
""")
    master_text = f"configs:\n- config_file: b.yaml\n  will_run: false\n# {dirs['foto']}\n"
    master = write(configs_dir, "master_config.yaml", master_text)

    plan = path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"])
    assert [(hit.config, hit.mapping_name, hit.field) for hit in plan.hits] == [
        ("configs/b.yaml", "bk / photos", "source_dir")
    ]
    path_replace.apply_path_change(plan)
    assert f'source_dir: "{dirs["neu"]}"' in read(backup)
    assert read(master) == master_text


def test_remove_drops_list_entries_and_reports_single_fields(configs_dir, dirs):
    path = write(configs_dir, "c.yaml", f"""will_run: true
actions:
- type: "DUPLICATE_REMOVER"
  mappings:
  - name: "dups"
    source_dirs:
    - "{dirs['other']}"
    exclude_dirs:
    - "{dirs['foto']}"   # gone
    - "{dirs['fotos']}"
- type: "NAMED_SUBDIR_COLLECTOR"
  mappings:
  - name: "collect"
    root: "{dirs['foto']}"
    subdir_names: ["a"]
""")
    plan = path_replace.plan_path_change("remove", dirs["foto"])
    kinds = {hit.field: hit.kind for hit in plan.hits}
    assert kinds == {"exclude_dirs[0]": path_replace.HIT_REMOVE, "root": path_replace.HIT_MANUAL}

    path_replace.apply_path_change(plan)
    text = read(path)
    assert f'"{dirs["foto"]}"   # gone' not in text
    assert f'- "{dirs["fotos"]}"' in text
    assert f'root: "{dirs["foto"]}"' in text


def test_remove_from_a_flow_list_keeps_the_rest_of_the_line(configs_dir, dirs):
    text = renamer_and_dups(dirs)
    path = write(configs_dir, "a.yaml", text)
    plan = path_replace.plan_path_change("remove", f"{dirs['foto']}/keep")
    result = path_replace.apply_path_change(plan)
    assert result.reformatted == []
    assert read(path) == text.replace(f'["{dirs["foto"]}/keep", "{dirs["other"]}"]', f'["{dirs["other"]}"]')


def test_removing_the_last_required_location_is_manual(configs_dir, dirs):
    write(configs_dir, "d.yaml", f"""will_run: true
actions:
- type: "TRASH_REMOVER"
  mappings:
  - name: "trash"
    directories:
    - "{dirs['foto']}/a"
    - "{dirs['foto']}/b"
""")
    plan = path_replace.plan_path_change("remove", dirs["foto"])
    assert [hit.kind for hit in plan.hits] == [path_replace.HIT_MANUAL, path_replace.HIT_MANUAL]


def test_user_home_placeholder_is_kept(configs_dir, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    path = write(configs_dir, "e.yaml", """will_run: true
actions:
- type: "ARCHIVE_EXTRACTOR"
  mappings:
  - name: "zips"
    search_dir: "{{USER_HOME}}/Downloads/alt"
    target_dir: "{{USER_HOME}}/Downloads/alt/out"
""")
    plan = path_replace.plan_path_change("replace", "{{USER_HOME}}/Downloads/alt", "{{USER_HOME}}/Downloads/neu")
    path_replace.apply_path_change(plan)
    text = read(path)
    assert 'search_dir: "{{USER_HOME}}/Downloads/neu"' in text
    assert 'target_dir: "{{USER_HOME}}/Downloads/neu/out"' in text


def test_relative_exclude_dirs_follow_their_root(configs_dir, dirs):
    path = write(configs_dir, "f.yaml", f"""will_run: true
actions:
- type: "TRASH_REMOVER"
  mappings:
  - name: "moved root"
    directories:
    - root: "{dirs['foto']}"
      exclude_dirs: ["keep"]
  - name: "inside root"
    directories:
    - root: "{dirs['other']}"
      exclude_dirs: ["old/keep"]
""")
    plan = path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"])
    assert [hit.field for hit in plan.hits] == ["directories[0].root"]

    plan = path_replace.plan_path_change("replace", f"{dirs['other']}/old", f"{dirs['other']}/new")
    (hit,) = plan.hits
    assert hit.field == "directories[0].exclude_dirs[0]"
    assert hit.new_value == "new/keep"
    path_replace.apply_path_change(plan)
    assert 'exclude_dirs: ["new/keep"]' in read(path)


def test_rename_tag_counts_only_for_move_files(configs_dir, dirs):
    write(configs_dir, "g.yaml", f"""will_run: true
actions:
- type: "RENAMER"
  mappings:
  - name: "rename"
    function: "rename_by_mtime"
    locations: ["{dirs['other']}"]
    mappings:
    - search_patterns: "*.jpg"
      rename_tag: "{dirs['foto']}/x"
""")
    assert path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"]).hits == []


def test_undo_restores_the_last_change(configs_dir, dirs):
    text = renamer_and_dups(dirs)
    path = write(configs_dir, "a.yaml", text)
    path_replace.apply_path_change(path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"]))
    assert path_replace.can_undo()
    restored, skipped = path_replace.undo_last_change()
    assert restored == [path] and skipped == []
    assert read(path) == text
    assert not path_replace.can_undo()


def test_undo_leaves_a_file_changed_since(configs_dir, dirs):
    path = write(configs_dir, "a.yaml", renamer_and_dups(dirs))
    path_replace.apply_path_change(path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"]))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("# edited by hand\n")
    restored, skipped = path_replace.undo_last_change()
    assert restored == []
    assert skipped[0][0] == path


def test_file_changed_since_the_search_is_skipped(configs_dir, dirs):
    path = write(configs_dir, "a.yaml", renamer_and_dups(dirs))
    plan = path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"])
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("# edited\n")
    result = path_replace.apply_path_change(plan)
    assert result.written == []
    assert result.skipped[0][0] == "configs/a.yaml"


def test_skip_configs_are_left_alone(configs_dir, dirs):
    text = renamer_and_dups(dirs)
    path = write(configs_dir, "a.yaml", text)
    plan = path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"])
    result = path_replace.apply_path_change(plan, skip_configs={"configs/a.yaml"})
    assert result.written == []
    assert read(path) == text


def test_new_path_that_does_not_exist_is_a_note_on_the_hit(configs_dir, dirs, tmp_path):
    write(configs_dir, "a.yaml", renamer_and_dups(dirs))
    plan = path_replace.plan_path_change("replace", dirs["foto"], posix_path(str(tmp_path / "nowhere")))
    assert all(hit.kind == path_replace.HIT_REPLACE and hit.message for hit in plan.hits)


def test_invalid_input_is_refused(dirs):
    with pytest.raises(ValueError):
        path_replace.plan_path_change("replace", "", dirs["neu"])
    with pytest.raises(ValueError):
        path_replace.plan_path_change("replace", dirs["foto"], dirs["foto"])
    with pytest.raises(ValueError):
        path_replace.plan_path_change("replace", "relative/path", dirs["neu"])


def test_find_missing_directories_groups_references(configs_dir, dirs, tmp_path):
    gone = posix_path(str(tmp_path / "gone"))
    write(configs_dir, "h.yaml", f"""will_run: true
actions:
- type: "DIRECTORY_OBSERVER"
  mappings:
  - name: "watch"
    extra_dirs: ["{gone}", "{dirs['other']}"]
    exclude_dirs: ["{gone}"]
""")
    missing, errors = path_replace.find_missing_directories()
    assert errors == []
    (entry,) = missing
    assert entry.status == "missing"
    assert [ref["field"] for ref in entry.references] == ["extra_dirs[0]", "exclude_dirs[0]"]


def test_mcp_preview_matches_the_plan_and_writes_nothing(configs_dir, dirs):
    from extensions.mcp_server import MCPServerExtension

    text = renamer_and_dups(dirs)
    path = write(configs_dir, "a.yaml", text)
    server = MCPServerExtension(session_resolver=lambda: None, host="localhost", port=6200, token="")
    result = server.dispatch(
        "preview_path_replacement", {"old_path": dirs["foto"], "new_path": dirs["neu"]}
    )
    plan = path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"])
    assert [h["id"] for h in result["hits"]] == [h.hit_id for h in plan.hits]
    assert read(path) == text

    missing = server.dispatch("list_missing_directories")
    assert "missing" in missing


def test_missing_ruamel_is_a_clear_error_not_zero_hits(configs_dir, dirs, monkeypatch):
    import sys

    from extensions.mcp_server import MCPServerExtension, MCPToolError

    write(configs_dir, "a.yaml", renamer_and_dups(dirs))
    monkeypatch.setitem(sys.modules, "ruamel.yaml", None)  # makes the import fail
    with pytest.raises(path_replace.MissingDependencyError, match="pip install ruamel.yaml"):
        path_replace.plan_path_change("replace", dirs["foto"], dirs["neu"])
    with pytest.raises(path_replace.MissingDependencyError):
        path_replace.find_missing_directories()

    server = MCPServerExtension(session_resolver=lambda: None, host="localhost", port=6200, token="")
    with pytest.raises(MCPToolError, match="ruamel.yaml"):
        server.dispatch("preview_path_replacement", {"old_path": dirs["foto"], "new_path": dirs["neu"]})
