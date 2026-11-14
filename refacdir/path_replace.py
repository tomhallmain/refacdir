"""
Replace or remove a directory path in every config file at once.

Only directory-valued fields are touched; ``PATH_FIELDS`` lists them per
action type. ``plan_path_change`` finds every hit without writing,
``apply_path_change`` writes the hits chosen from that plan, and
``undo_last_change`` restores the files the last apply changed.

Files are read and written with ruamel.yaml in round-trip mode. A changed
value is first edited in place in the file's text, at the position ruamel
reports for it, so comments and layout stay exactly as they were. Only when
that edit cannot be verified (the reloaded file must equal the intended
result under both ruamel and PyYAML, which ``BatchJob`` reads with) is the
file dumped by ruamel instead, which keeps comments and quoting but can
change indentation; such files are reported as reformatted.
"""
import hashlib
import io
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import yaml as pyyaml

from refacdir.batch import ActionType, BatchArgs
from refacdir.utils.cache_paths import refacdir_cache_dir
from refacdir.utils.logger import setup_logger
from refacdir.utils.translations import LocalizedText, _
from refacdir.utils.utils import Utils

logger = setup_logger("path_replace")

MODE_REPLACE = "replace"
MODE_REMOVE = "remove"

# Hit kinds. "replace"/"remove" can be applied; "manual" and "note" are reported only.
HIT_REPLACE = "replace"
HIT_REMOVE = "remove"
HIT_MANUAL = "manual"
HIT_NOTE = "note"

LOCATION = "location"    # one location: a path string or {root, exclude_dirs}
LOCATIONS = "locations"  # a list of locations

# Directory-valued fields per action type. A nested dict is a list of
# sub-mappings with its own fields (BACKUP's backup_mappings). RENAMER's
# rename_tag is also a directory in move_files groups; _iter_refs handles it.
PATH_FIELDS = {
    ActionType.BACKUP: {
        "backup_mappings": {
            "source_dir": LOCATION,
            "target_dir": LOCATION,
            "exclude_dirs": LOCATIONS,
            "exclude_removal_dirs": LOCATIONS,
        },
    },
    ActionType.RENAMER: {"locations": LOCATIONS},
    ActionType.DUPLICATE_REMOVER: {
        "source_dirs": LOCATIONS,
        "exclude_dirs": LOCATIONS,
        "preferred_delete_dirs": LOCATIONS,
    },
    ActionType.DIRECTORY_OBSERVER: {
        "sortable_dirs": LOCATIONS,
        "extra_dirs": LOCATIONS,
        "parent_dirs": LOCATIONS,
        "exclude_dirs": LOCATIONS,
    },
    ActionType.DIRECTORY_FLATTENER: {"location": LOCATION},
    ActionType.IMAGE_CATEGORIZER: {"source_dir": LOCATION, "exclude_dirs": LOCATIONS},
    ActionType.NAMED_SUBDIR_COLLECTOR: {"root": LOCATION},
    ActionType.ARCHIVE_EXTRACTOR: {"search_dir": LOCATION, "target_dir": LOCATION},
    ActionType.TRASH_REMOVER: {"directories": LOCATIONS},
}

# Lists a mapping cannot run without; removing their last entry is left to the user.
_REQUIRED_LISTS = {
    (ActionType.RENAMER, "locations"),
    (ActionType.DUPLICATE_REMOVER, "source_dirs"),
    (ActionType.TRASH_REMOVER, "directories"),
}

_BACKUP_DIR_NAME = "path_replace_backups"
_MANIFEST = "manifest.json"
_KEEP_BACKUPS = 10
_PLAIN_SAFE = re.compile(r"[A-Za-z0-9_./~\\][A-Za-z0-9_./~\\ ()+@=:-]*")
_YAML11_SPECIAL = {"y", "n", "yes", "no", "on", "off", "true", "false", "null", "~"}


# ----- paths -----

def _expand(path: str) -> str:
    return Utils.fix_path(path)


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _is_under(path: str, ancestor: str) -> bool:
    """Both normalized with ``_key``; matches at path-segment boundaries only."""
    if path == ancestor:
        return True
    return path.startswith(ancestor.rstrip(os.sep) + os.sep)


def _sep_style(original: str) -> Optional[str]:
    if "\\" in original:
        return "\\"
    if "/" in original:
        return "/"
    return None


def _apply_sep_style(path: str, style: Optional[str]) -> str:
    if style == "\\":
        return path.replace("/", "\\")
    if style == "/":
        return path.replace("\\", "/")
    return path


def _replace_prefix(expanded: str, old_expanded: str, new_expanded: str) -> str:
    rest = expanded[len(old_expanded.rstrip(os.sep)):].lstrip(os.sep)
    return os.path.join(new_expanded, rest) if rest else new_expanded


def rewrite_path(value: str, old_path: str, new_path: str) -> str:
    """
    ``value`` with its ``old_path`` part replaced by ``new_path``, keeping the
    rest of it, the ``{{USER_HOME}}`` placeholder when the result is still in
    the home directory, and the separator style ``value`` was written in.
    """
    result = _replace_prefix(_expand(value), _expand(old_path), _expand(new_path))
    if "{{USER_HOME}}" in value:
        home = os.path.normpath(os.path.expanduser("~"))
        if _is_under(_key(result), _key(home)):
            result = "{{USER_HOME}}" + result[len(home):]
    return _apply_sep_style(result, _sep_style(value))


# ----- walking a config -----

@dataclass
class _PathRef:
    keys: tuple                 # address of the scalar in the document
    value: str
    action_type: ActionType
    mapping_name: str
    field: str
    element_keys: Optional[tuple] = None  # list element removed by "remove"; None for a single field
    list_keys: Optional[tuple] = None
    required_list: bool = False
    root_value: Optional[str] = None      # set for an exclude_dirs entry inside a location dict


def _iter_location(value, keys, label, ctx, element_keys=None, list_keys=None, required=False):
    action_type, mapping_name = ctx
    if isinstance(value, str):
        yield _PathRef(keys, value, action_type, mapping_name, label, element_keys, list_keys, required)
    elif isinstance(value, dict):
        root = value.get("root")
        if isinstance(root, str):
            yield _PathRef(keys + ("root",), root, action_type, mapping_name, label + ".root",
                           element_keys, list_keys, required)
        excludes = value.get("exclude_dirs")
        if isinstance(excludes, list):
            for j, entry in enumerate(excludes):
                if isinstance(entry, str):
                    entry_keys = keys + ("exclude_dirs", j)
                    yield _PathRef(entry_keys, entry, action_type, mapping_name,
                                   f"{label}.exclude_dirs[{j}]", entry_keys, keys + ("exclude_dirs",),
                                   False, root if isinstance(root, str) else None)


def _iter_fields(container, spec, base, ctx):
    action_type, mapping_name = ctx
    for field_name, kind in spec.items():
        value = container.get(field_name)
        if value is None:
            continue
        if isinstance(kind, dict):
            if isinstance(value, list):
                for i, sub in enumerate(value):
                    if isinstance(sub, dict):
                        sub_name = f"{mapping_name} / {sub.get('name', i)}"
                        yield from _iter_fields(sub, kind, base + (field_name, i), (action_type, sub_name))
        elif kind == LOCATION:
            yield from _iter_location(value, base + (field_name,), field_name, ctx)
        elif kind == LOCATIONS and isinstance(value, list):
            required = (action_type, field_name) in _REQUIRED_LISTS
            for i, item in enumerate(value):
                item_keys = base + (field_name, i)
                yield from _iter_location(item, item_keys, f"{field_name}[{i}]", ctx,
                                          item_keys, base + (field_name,), required)


def _iter_refs(data):
    """Every directory-valued scalar in one config document."""
    if not isinstance(data, dict):
        return
    actions = data.get("actions")
    if not isinstance(actions, list):
        return
    for ai, action in enumerate(actions):
        if not isinstance(action, dict):
            continue
        try:
            action_type = ActionType[str(action.get("type"))]
        except KeyError:
            continue
        mappings = action.get("mappings")
        if not isinstance(mappings, list):
            continue
        for mi, mapping in enumerate(mappings):
            if not isinstance(mapping, dict):
                continue
            ctx = (action_type, str(mapping.get("name", mi)))
            base = ("actions", ai, "mappings", mi)
            yield from _iter_fields(mapping, PATH_FIELDS.get(action_type, {}), base, ctx)
            if action_type == ActionType.RENAMER and mapping.get("function") in ("move_files", "batch_move_files"):
                rules = mapping.get("mappings")
                for ri, rule in enumerate(rules if isinstance(rules, list) else []):
                    if isinstance(rule, dict) and isinstance(rule.get("rename_tag"), str) and rule["rename_tag"]:
                        yield _PathRef(base + ("mappings", ri, "rename_tag"), rule["rename_tag"],
                                       action_type, ctx[1], f"mappings[{ri}].rename_tag")


def _ref_abs_path(ref: _PathRef) -> Optional[str]:
    """Absolute expanded path of a reference, or None for a relative path with no root."""
    expanded = _expand(ref.value)
    if ref.root_value is not None and not os.path.isabs(expanded):
        return os.path.join(_expand(ref.root_value), expanded)
    return expanded if os.path.isabs(expanded) else None


# ----- YAML access -----

class MissingDependencyError(ImportError):
    """ruamel.yaml is not installed. Raised as is, never reported per config file."""


def _ruamel():
    try:
        from ruamel.yaml import YAML
    except ImportError as e:
        raise MissingDependencyError(
            LocalizedText(
                "Replace Paths needs the ruamel.yaml package, which is not installed. "
                "Install it with: pip install ruamel.yaml"
            )
        ) from e

    yaml = YAML()  # round-trip
    yaml.preserve_quotes = True
    yaml.width = 4096
    return yaml


def _load_rt(text: str):
    return _ruamel().load(text)


def _to_plain(node):
    if isinstance(node, dict):
        return {(str(k) if isinstance(k, str) else k): _to_plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_to_plain(v) for v in node]
    if isinstance(node, str):
        return str(node)
    return node


def _get(node, keys):
    for key in keys:
        node = node[key]
    return node


def _apply_ops(data, ops):
    """Apply ``(op, keys, new_value)`` ops to a plain or ruamel structure, in place."""
    for op, keys, new_value in ops:
        if op == HIT_REPLACE:
            parent = _get(data, keys[:-1])
            old = parent[keys[-1]]
            # Keep a ruamel quoted-scalar type, so the dump quotes it the same way.
            if type(old) is not str and isinstance(old, str):
                try:
                    new_value = type(old)(new_value)
                except Exception:
                    pass
            parent[keys[-1]] = new_value
    # Deepest first, then highest index first, so no removal shifts another's address.
    removals = sorted((keys for op, keys, _v in ops if op == HIT_REMOVE), key=lambda k: (len(k), k[-1]), reverse=True)
    for keys in removals:
        del _get(data, keys[:-1])[keys[-1]]
    return data


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ----- plan -----

@dataclass
class PathHit:
    hit_id: str
    config: str
    action_type: str
    mapping_name: str
    field: str
    old_value: str
    new_value: Optional[str]
    kind: str
    message: str = ""
    keys: tuple = ()
    list_keys: Optional[tuple] = None
    required_list: bool = False

    @property
    def applicable(self) -> bool:
        return self.kind in (HIT_REPLACE, HIT_REMOVE)

    def to_dict(self) -> dict:
        return {
            "id": self.hit_id,
            "config": self.config,
            "action_type": self.action_type,
            "mapping": self.mapping_name,
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "kind": self.kind,
            "message": str(self.message),
        }


@dataclass
class _FileState:
    config: str
    abs_path: str
    text: str
    sha: str


@dataclass
class PathPlan:
    mode: str
    old_path: str
    new_path: Optional[str]
    hits: list = field(default_factory=list)
    files: dict = field(default_factory=dict)   # config -> _FileState
    errors: list = field(default_factory=list)  # (config, LocalizedText)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "old_path": self.old_path,
            "new_path": self.new_path,
            "hits": [hit.to_dict() for hit in self.hits],
            "unreadable_configs": [{"config": c, "error": str(e)} for c, e in self.errors],
        }


def config_files() -> list:
    """``(config key, absolute path)`` for every config the discovery finds, enabled or not."""
    return [(key, BatchArgs.config_yaml_abs_path(key)) for key in BatchArgs.discover_runnable_config_paths()]


def _read_configs():
    for config, abs_path in config_files():
        try:
            with open(abs_path, encoding="utf-8") as handle:
                text = handle.read()
            data = _load_rt(text)
        except MissingDependencyError:
            raise
        except Exception as e:
            yield config, abs_path, None, None, LocalizedText("could not be read: {0}", e)
            continue
        yield config, abs_path, text, data, None


def plan_path_change(mode: str, old_path: str, new_path: Optional[str] = None) -> PathPlan:
    """Find every hit for ``old_path`` in every config; nothing is written."""
    if mode not in (MODE_REPLACE, MODE_REMOVE):
        raise ValueError(LocalizedText("Invalid mode {0}", mode))
    if not isinstance(old_path, str) or not old_path.strip():
        raise ValueError(LocalizedText("A path to replace is required"))
    old_expanded = _expand(old_path.strip())
    if not os.path.isabs(old_expanded):
        raise ValueError(LocalizedText("The path to replace must be absolute: {0}", old_path))
    if mode == MODE_REPLACE:
        if not isinstance(new_path, str) or not new_path.strip():
            raise ValueError(LocalizedText("A new path is required"))
        new_expanded = _expand(new_path.strip())
        if not os.path.isabs(new_expanded):
            raise ValueError(LocalizedText("The new path must be absolute: {0}", new_path))
        if _key(new_expanded) == _key(old_expanded):
            raise ValueError(LocalizedText("The new path is the same as the old one"))
    plan = PathPlan(mode, old_path.strip(), new_path.strip() if new_path else None)
    old_key = _key(old_expanded)

    for config, abs_path, text, data, error in _read_configs():
        if error is not None:
            plan.errors.append((config, error))
            continue
        plan.files[config] = _FileState(config, abs_path, text, _sha(text))
        file_hits = []
        for ref in _iter_refs(data):
            hit = _plan_ref(ref, plan, old_key)
            if hit is not None:
                hit.config = config
                file_hits.append(hit)
        if mode == MODE_REMOVE:
            file_hits = _drop_covered_removals(file_hits)
            _protect_required_lists(file_hits, data)
        for i, hit in enumerate(file_hits):
            hit.hit_id = f"{config}#{i}"
        plan.hits.extend(file_hits)
    return plan


def _plan_ref(ref: _PathRef, plan: PathPlan, old_key: str) -> Optional[PathHit]:
    abs_path = _ref_abs_path(ref)
    if abs_path is None or not _is_under(_key(abs_path), old_key):
        return None
    if ref.root_value is not None and not os.path.isabs(_expand(ref.value)):
        root_expanded = _expand(ref.root_value)
        if _is_under(_key(root_expanded), old_key):
            return None  # moves or goes with its root; the root's own hit covers it
    hit = PathHit("", "", ref.action_type.name, ref.mapping_name, ref.field, ref.value, None, HIT_MANUAL,
                  keys=ref.keys)

    if plan.mode == MODE_REMOVE:
        if ref.element_keys is None:
            hit.message = LocalizedText("a single path field cannot be removed; edit this mapping by hand")
        else:
            hit.kind = HIT_REMOVE
            hit.keys = ref.element_keys
            hit.list_keys = ref.list_keys
            hit.required_list = ref.required_list
        return hit

    new_abs = _replace_prefix(abs_path, _expand(plan.old_path), _expand(plan.new_path))
    if ref.root_value is not None and not os.path.isabs(_expand(ref.value)):
        root_expanded = _expand(ref.root_value)
        if not _is_under(_key(new_abs), _key(root_expanded)):
            hit.kind = HIT_NOTE
            hit.message = LocalizedText(
                "relative exclude_dirs entry would leave its root {0}; edit this mapping by hand", ref.root_value
            )
            return hit
        relative = os.path.relpath(new_abs, root_expanded)
        hit.new_value = _apply_sep_style(relative, _sep_style(ref.value))
    else:
        hit.new_value = rewrite_path(ref.value, plan.old_path, plan.new_path)
    hit.kind = HIT_REPLACE
    if not os.path.isdir(new_abs):
        hit.message = LocalizedText("the new directory does not exist (yet): {0}", new_abs)
    return hit


def _drop_covered_removals(hits: list) -> list:
    """Drop removals inside an element another removal already takes out whole."""
    removed = {h.keys for h in hits if h.kind == HIT_REMOVE}
    kept, seen = [], set()
    for hit in hits:
        if hit.kind == HIT_REMOVE:
            if hit.keys in seen or any(hit.keys[:n] in removed for n in range(1, len(hit.keys))):
                continue
            seen.add(hit.keys)
        kept.append(hit)
    return kept


def _protect_required_lists(hits: list, data):
    """Turn removals that would empty a required list into manual hits."""
    by_list = {}
    for hit in hits:
        if hit.kind == HIT_REMOVE and hit.required_list:
            by_list.setdefault(hit.list_keys, []).append(hit)
    for list_keys, removals in by_list.items():
        if len({h.keys for h in removals}) >= len(_get(data, list_keys)):
            for hit in removals:
                hit.kind = HIT_MANUAL
                hit.message = LocalizedText("removing this would leave {0} empty; edit this mapping by hand", list_keys[-1])


# ----- writing -----

def _scalar_end(line: str, col: int, flow: bool) -> Optional[int]:
    """End column of the scalar starting at ``col``, or None if it does not end on this line."""
    if col >= len(line):
        return None
    quote = line[col]
    if quote == '"':
        i = col + 1
        while i < len(line):
            if line[i] == "\\":
                i += 2
            elif line[i] == '"':
                return i + 1
            else:
                i += 1
        return None
    if quote == "'":
        i = col + 1
        while i < len(line):
            if line[i] == "'":
                if i + 1 < len(line) and line[i + 1] == "'":
                    i += 2
                    continue
                return i + 1
            i += 1
        return None
    end = len(line)
    comment = line.find(" #", col)
    if comment != -1:
        end = comment
    if flow:
        for stop in (",", "]", "}"):
            pos = line.find(stop, col)
            if pos != -1:
                end = min(end, pos)
    while end > col and line[end - 1] in " \t\r":
        end -= 1
    return end


def _render_scalar(value: str, style: str, flow: bool) -> str:
    if style == "'":
        return "'" + value.replace("'", "''") + "'"
    if style != '"' and _PLAIN_SAFE.fullmatch(value) and ": " not in value and not value.endswith(":") \
            and value.lower() not in _YAML11_SPECIAL and not (flow and any(c in value for c in ",[]{}")):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _position(data, keys):
    """``(line, col)`` ruamel recorded for the scalar at ``keys``."""
    parent = _get(data, keys[:-1])
    if isinstance(keys[-1], int):
        return parent.lc.item(keys[-1])
    return parent.lc.value(keys[-1])


def _is_flow(seq) -> bool:
    try:
        return bool(seq.fa.flow_style())
    except Exception:
        return False


def _edit_text(text: str, data, ops) -> Optional[str]:
    """``text`` with ``ops`` applied in place, or None when an op cannot be located."""
    lines = text.split("\n")
    edits = []          # (line, start, end, replacement)
    delete_lines = set()
    flow_removals = {}  # list keys -> removed indices
    try:
        for op, keys, new_value in ops:
            parent = _get(data, keys[:-1])
            flow = isinstance(parent, (list, dict)) and _is_flow(parent)
            if op == HIT_REPLACE:
                line, col = _position(data, keys)
                end = _scalar_end(lines[line], col, flow)
                if end is None:
                    return None
                style = lines[line][col]
                edits.append((line, col, end, _render_scalar(new_value, style, flow)))
                continue
            if flow:
                flow_removals.setdefault(keys[:-1], set()).add(keys[-1])
                continue
            item = parent[keys[-1]]
            if not isinstance(item, str):
                return None
            line, col = parent.lc.item(keys[-1])
            if lines[line][:col].strip() != "-":
                return None
            end = _scalar_end(lines[line], col, False)
            rest = lines[line][end:].strip() if end is not None else None  # strip() also drops a CR
            if rest is None or (rest and not rest.startswith("#")):
                return None
            delete_lines.add(line)
        for list_keys, removed in flow_removals.items():
            seq = _get(data, list_keys)
            positions = [seq.lc.item(i) for i in range(len(seq))]
            line = positions[0][0]
            if any(p[0] != line for p in positions):
                return None
            items = []
            for i, (_l, col) in enumerate(positions):
                end = _scalar_end(lines[line], col, True)
                if end is None:
                    return None
                items.append(lines[line][col:end])
            open_pos = lines[line].rfind("[", 0, positions[0][1])
            close_pos = lines[line].find("]", _scalar_end(lines[line], positions[-1][1], True))
            if open_pos == -1 or close_pos == -1:
                return None
            kept = [text_item for i, text_item in enumerate(items) if i not in removed]
            edits.append((line, open_pos, close_pos + 1, "[" + ", ".join(kept) + "]"))
    except Exception as e:
        logger.debug(f"In-place edit not possible: {e}")
        return None

    for line, start, end, replacement in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        lines[line] = lines[line][:start] + replacement + lines[line][end:]
    return "\n".join(line for i, line in enumerate(lines) if i not in delete_lines)


def _dump(data, original_text: str) -> str:
    yaml = _ruamel()
    from ruamel.yaml.util import load_yaml_guess_indent

    try:
        _data, indent, block_seq_indent = load_yaml_guess_indent(original_text)
        yaml.indent(mapping=indent, sequence=indent, offset=block_seq_indent)
    except Exception:
        pass
    stream = io.StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()


def _load_py(text: str):
    """The document as ``BatchJob`` reads it."""
    return pyyaml.load(text, Loader=pyyaml.FullLoader)


def _verified(new_text: str, expected_rt, expected_py) -> bool:
    try:
        return _to_plain(_load_rt(new_text)) == expected_rt and _load_py(new_text) == expected_py
    except Exception:
        return False


def _render_file(state: _FileState, ops) -> tuple:
    """``(new_text, reformatted)`` for one file, or raise if no verified result exists."""
    data = _load_rt(state.text)
    expected_rt = _apply_ops(_to_plain(data), ops)
    expected_py = _apply_ops(_load_py(state.text), ops)
    edited = _edit_text(state.text, data, ops)
    if edited is not None and _verified(edited, expected_rt, expected_py):
        return edited, False
    dumped = _dump(_apply_ops(data, ops), state.text)
    if _verified(dumped, expected_rt, expected_py):
        return dumped, True
    raise Exception(LocalizedText("{0}: the change could not be written without altering other values", state.config))


@dataclass
class ApplyResult:
    written: list = field(default_factory=list)      # configs
    reformatted: list = field(default_factory=list)  # configs dumped by ruamel
    skipped: list = field(default_factory=list)      # (config, LocalizedText)
    warnings: list = field(default_factory=list)     # (config, LocalizedText)
    changed_values: int = 0


def apply_path_change(plan: PathPlan, hit_ids=None, skip_configs=()) -> ApplyResult:
    """
    Write the plan's applicable hits (all, or those in ``hit_ids``). Files
    in ``skip_configs`` or changed on disk since the plan are left alone.
    Each written file is backed up first, re-read, and its actions are
    test-constructed; a file that no longer parses is restored at once.
    """
    result = ApplyResult()
    wanted = None if hit_ids is None else set(hit_ids)
    chosen = [h for h in plan.hits if h.applicable and (wanted is None or h.hit_id in wanted)]
    by_config = {}
    for hit in chosen:
        by_config.setdefault(hit.config, []).append(hit)

    rendered = {}
    for config, hits in by_config.items():
        state = plan.files[config]
        if config in skip_configs:
            result.skipped.append((config, LocalizedText("open in the config editor with unsaved changes")))
            continue
        try:
            with open(state.abs_path, encoding="utf-8") as handle:
                current = handle.read()
        except OSError as e:
            result.skipped.append((config, LocalizedText("could not be read: {0}", e)))
            continue
        if _sha(current) != state.sha:
            result.skipped.append((config, LocalizedText("changed since the search; search again")))
            continue
        ops = [(h.kind, h.keys, h.new_value) for h in hits]
        try:
            rendered[config] = (_render_file(state, ops), len(hits))
        except MissingDependencyError:
            raise
        except Exception as e:
            result.skipped.append((config, e.args[0] if e.args else LocalizedText("{0}", e)))

    if not rendered:
        return result

    backup_dir = _new_backup_dir()
    manifest = {"created": datetime.now().isoformat(), "undone": False, "files": []}
    for config, ((new_text, reformatted), count) in rendered.items():
        state = plan.files[config]
        backup_path = os.path.join(backup_dir, os.path.basename(state.abs_path))
        shutil.copy2(state.abs_path, backup_path)
        with open(state.abs_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(new_text)
        manifest["files"].append({"path": state.abs_path, "backup": backup_path, "sha256_after": _sha(new_text)})
        problems = validate_config_file(state.abs_path)
        if problems is None:
            shutil.copy2(backup_path, state.abs_path)
            manifest["files"].pop()
            result.skipped.append((config, LocalizedText("the written file did not load; restored from backup")))
            continue
        result.written.append(config)
        result.changed_values += count
        if reformatted:
            result.reformatted.append(config)
        result.warnings.extend((config, problem) for problem in problems)
    with open(os.path.join(backup_dir, _MANIFEST), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    _prune_backups()
    logger.info(
        _("Path change: {0} value(s) changed in {1} config file(s)").format(result.changed_values, len(result.written))
    )
    return result


def validate_config_file(abs_path: str):
    """
    Load one config as ``BatchJob`` does and test-construct each of its
    mappings. Returns a list of ``LocalizedText`` problems, or None when the
    file does not load at all. Definition registries are restored afterwards.
    """
    from refacdir.batch import BatchJob
    from refacdir.filename_ops import FilenameMappingDefinition, FiletypesDefinition

    try:
        with open(abs_path, encoding="utf-8") as handle:
            data = pyyaml.load(handle, Loader=pyyaml.FullLoader)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    saved_functions = dict(FilenameMappingDefinition.NAMED_FUNCTIONS)
    saved_definitions = dict(FiletypesDefinition.NAMED_DEFINITIONS)
    problems = []
    try:
        FilenameMappingDefinition.add_named_functions(data.get("filename_mapping_functions") or [])
        FiletypesDefinition.add_named_definitions(data.get("filetype_definitions") or [])
        job = BatchJob(BatchArgs(configs={"__path_replace_validation__.yaml": False}))
        for action in data.get("actions") or []:
            try:
                action_type = ActionType[action["type"]]
            except Exception:
                continue
            if action_type == ActionType.IMAGE_CATEGORIZER:
                continue  # constructing it loads the CLIP model
            method = "construct_batch_renamer" if action_type == ActionType.RENAMER else f"construct_{action_type.get_varname()}"
            for mapping in action.get("mappings") or []:
                try:
                    getattr(job, method)(mapping)
                except Exception as e:
                    name = mapping.get("name", "?") if isinstance(mapping, dict) else "?"
                    problems.append(LocalizedText("{0} \"{1}\": {2}", action_type.name, name, e))
    except Exception as e:
        problems.append(LocalizedText("{0}", e))
    finally:
        FilenameMappingDefinition.NAMED_FUNCTIONS.clear()
        FilenameMappingDefinition.NAMED_FUNCTIONS.update(saved_functions)
        FiletypesDefinition.NAMED_DEFINITIONS.clear()
        FiletypesDefinition.NAMED_DEFINITIONS.update(saved_definitions)
    return problems


# ----- backups and undo -----

def _backup_root() -> str:
    return os.path.join(refacdir_cache_dir(), _BACKUP_DIR_NAME)


def _new_backup_dir() -> str:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    path = os.path.join(_backup_root(), stamp)
    os.makedirs(path, exist_ok=True)
    return path


def _backup_dirs() -> list:
    root = _backup_root()
    if not os.path.isdir(root):
        return []
    return sorted(
        (os.path.join(root, name) for name in os.listdir(root) if os.path.isfile(os.path.join(root, name, _MANIFEST))),
        reverse=True,
    )


def _prune_backups():
    for path in _backup_dirs()[_KEEP_BACKUPS:]:
        shutil.rmtree(path, ignore_errors=True)


def _last_manifest():
    dirs = _backup_dirs()
    if not dirs:
        return None, None
    path = os.path.join(dirs[0], _MANIFEST)
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    return path, manifest


def can_undo() -> bool:
    _path, manifest = _last_manifest()
    return bool(manifest and not manifest.get("undone") and manifest.get("files"))


def undo_last_change() -> tuple:
    """
    Restore the files of the last apply. Returns ``(restored, skipped)``: the
    restored paths, and ``(path, LocalizedText)`` for files changed since then,
    which are left as they are.
    """
    manifest_path, manifest = _last_manifest()
    if manifest is None or manifest.get("undone"):
        return [], []
    restored, skipped = [], []
    for entry in manifest.get("files", []):
        path = entry["path"]
        try:
            with open(path, encoding="utf-8") as handle:
                current = handle.read()
        except OSError as e:
            skipped.append((path, LocalizedText("could not be read: {0}", e)))
            continue
        if _sha(current) != entry["sha256_after"]:
            skipped.append((path, LocalizedText("changed since the path change; left as it is")))
            continue
        shutil.copy2(entry["backup"], path)
        restored.append(path)
    manifest["undone"] = True
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    logger.info(_("Path change undone: {0} config file(s) restored").format(len(restored)))
    return restored, skipped


# ----- missing directories -----

@dataclass
class MissingDirectory:
    path: str
    status: str  # "missing" or "unreachable"
    references: list = field(default_factory=list)  # dicts: config, action_type, mapping, field, value

    def to_dict(self) -> dict:
        return {"path": self.path, "status": self.status, "references": list(self.references)}


def _drive_unreachable(path: str) -> bool:
    drive = os.path.splitdrive(path)[0]
    return bool(drive) and not os.path.exists(drive + os.sep)


def find_missing_directories() -> tuple:
    """
    ``(missing, errors)``: every referenced absolute directory that does not
    exist, grouped by path, and ``(config, LocalizedText)`` for unreadable
    configs. A path on a drive that is not connected is "unreachable".
    """
    grouped = {}
    errors = []
    checked_roots = set()
    for config, _abs_path, _text, data, error in _read_configs():
        if error is not None:
            errors.append((config, error))
            continue
        for ref in _iter_refs(data):
            abs_path = _ref_abs_path(ref)
            if abs_path is None:
                continue
            drive_root = os.path.splitdrive(abs_path)[0]
            if drive_root and drive_root not in checked_roots:
                checked_roots.add(drive_root)
                Utils.isdir_with_retry(drive_root + os.sep)  # wakes a sleeping external drive once
            if os.path.isdir(abs_path):
                continue
            entry = grouped.get(_key(abs_path))
            if entry is None:
                status = "unreachable" if _drive_unreachable(abs_path) else "missing"
                entry = grouped[_key(abs_path)] = MissingDirectory(os.path.normpath(abs_path), status)
            entry.references.append({
                "config": config,
                "action_type": ref.action_type.name,
                "mapping": ref.mapping_name,
                "field": ref.field,
                "value": ref.value,
            })
    return sorted(grouped.values(), key=lambda m: m.path.lower()), errors
