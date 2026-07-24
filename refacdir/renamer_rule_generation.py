import os
import re
import fnmatch
from collections import Counter, defaultdict


_SEPARATOR_RE = re.compile(r"[_\-\s]+")
_HEX_RE = re.compile(r"[0-9a-fA-F]{32,64}")
_DATEISH_RE = re.compile(
    r"(?:\d{4}-\d{2}-\d{2}(?:[T_ -]?\d{2}\d{2}\d{2}(?:\.\d+)?)?|\d{8}(?:[T_ -]?\d{6})?)"
)
_COPY_SUFFIX_RE = re.compile(r"\s*\(\d+\)$")
_DIGIT_RUN_RE = re.compile(r"\d+")
_MULTI_SPACE_RE = re.compile(r"\s+")
_STOPWORDS = {"the", "and", "new", "img", "image", "file", "copy"}

# Basenames that many unrelated sites/tools independently hand out as a "default"
# name, rather than anything the uploader/tool chose per-file — so unlike a
# hash/UUID collision (same name = same content), a collision here almost always
# means two *different* images that just happen to share a generic name. Grouped
# by where they come from:
_NOTORIOUS_DEFAULT_BASENAMES = [
    # YouTube's thumbnail CDN serves these exact names for every single video
    # (only the resolution differs), so downloading thumbnails from more than
    # one video guarantees a collision.
    "maxresdefault", "sddefault", "hqdefault", "mqdefault", "default",
    # Generic thumbnailing/proxy services and CDNs. More specific names come
    # before the shorter, more generic ones they contain as a prefix
    # ("imgproxy" before "img" below, "thumbnail" before "thumb" here) so
    # that if a file were ever eligible under more than one entry, the more
    # specific tag wins (see BatchRenamer._dedupe_cross_pattern_matches).
    "imgproxy", "thumbnail", "thumb",
    # Servers/tools that fall back to a generic Content-Disposition filename
    # instead of the original one.
    "download", "image", "img", "photo", "picture", "unknown", "index",
    # Screenshot tools and OS "paste"/save-as defaults, and generic
    # image-captioning/alt-text tools that write one generic name per
    # output rather than deriving it from the source image.
    "screenshot", "capture", "untitled", "caption",
]


# Static catalog of well-known filename shapes — unlike suggest_renamer_rules(),
# these don't require scanning any directory. A user must still explicitly pick
# one in the UI; nothing here is ever applied automatically.
_COMMON_PATTERN_PRESETS = [
    {
        "name": "Integer Basename",
        "search_patterns": "{{is_short_integer_filename}}",
        "rename_tag": "int_",
        "function_hint": "rename_by_ctime",
        "chain_parenthetical_indices": True,
        "reason": (
            'Filenames that are just a short number (up to 5 digits), e.g. "1234.jpg" — '
            "the same browser-download collision as the letter case: re-downloading "
            'saves it as "1234 (1).jpg", "1234 (2).jpg", etc. rather than overwriting it.'
        ),
    },
    {
        "name": "Single-Letter/Initialism Basename",
        "search_patterns": "{{is_short_alpha_filename}}",
        "rename_tag": "letter_",
        "function_hint": "rename_by_ctime",
        "chain_parenthetical_indices": True,
        "reason": (
            'Filenames that are just one or two letters, e.g. "O.jpg" or "R.png" — '
            "a known browser-download collision: re-downloading (or saving from a "
            'different tab/page) the same image saves it as "R (1).png", "R (2).png", '
            "etc. rather than overwriting it."
        ),
    },
    {
        "name": "Camera Photo (IMG_####)",
        "search_patterns": "IMG_",
        "rename_tag": "cam_",
        "function_hint": "rename_by_ctime",
        "reason": 'Default camera/phone photo naming, e.g. "IMG_1234.jpg".',
    },
    {
        "name": "Hash/UUID Basename",
        "search_patterns": "{{is_id_filename}}",
        "rename_tag": "id_",
        "function_hint": "rename_by_ctime",
        "reason": (
            "Filenames that look like a random ID or hash rather than a human-chosen "
            "name. Deliberately NOT paired with chain_parenthetical_indices: a "
            'collision here (e.g. two files both matching "{{is_id_filename}}") means '
            "the same content was downloaded twice, not just the same name — renaming "
            "would hide a real duplicate from the duplicate remover rather than "
            "resolve a naming coincidence."
        ),
    },
    {
        "name": "Notorious Default/Generic Filenames",
        # Each basename gets a literal "." appended so it only ever matches
        # as a whole basename ("imgproxy.png") — not as a prefix of some
        # unrelated longer name ("image_chroma_text_to_image_lora.json"
        # must NOT match the "image" entry). chain_parenthetical_indices
        # below still lets "imgproxy (4).png" match via the same rule after
        # its " (4)" duplicate-download index is stripped.
        "search_patterns": ", ".join(f"{name}.*" for name in _NOTORIOUS_DEFAULT_BASENAMES),
        # No rename_tag: each of these is a plain literal pattern, so
        # FilenameMappingDefinition.construct_mappings auto-derives a distinct
        # tag per pattern ("maxresdefault.*" -> "maxresdefault_", etc.) rather
        # than collapsing every match under one shared generic tag.
        "chain_parenthetical_indices": True,
        "function_hint": "rename_by_ctime",
        "reason": (
            "Basenames that many unrelated sites/tools hand out as a generic default "
            '(e.g. "maxresdefault"/"hqdefault" from YouTube thumbnails, or a server '
            'falling back to "image"/"download") rather than anything file-specific — '
            "collecting more than one is a near-certain collision. Unlike Hash/UUID "
            "Basename, a collision here means two different images share a generic "
            "name, not duplicate content, so renaming is the right fix. Each pattern "
            "keeps its own name as the rename tag (e.g. files matching "
            '"maxresdefault" become "maxresdefault_<timestamp>") instead of one '
            "shared generic tag. Only matches the exact basename plus extension (or "
            'plus a duplicate-download chain index, e.g. "imgproxy (4).png") — never '
            "as a prefix of a longer, unrelated name."
        ),
    },
]


def common_pattern_presets() -> list[dict]:
    """Static catalog of well-known filename shapes, independent of any directory scan."""
    return [dict(preset) for preset in _COMMON_PATTERN_PRESETS]


def _iter_files(directory: str, recursive: bool = False, max_files: int = 3000) -> list[dict]:
    files = []
    if not os.path.isdir(directory):
        return files

    if recursive:
        for root, _, names in os.walk(directory):
            rel_dir = os.path.relpath(root, directory).replace("\\", "/")
            if rel_dir == ".":
                rel_dir = ""
            for filename in names:
                files.append({"name": filename, "subdir": rel_dir})
                if len(files) >= max_files:
                    return files
    else:
        for entry in os.scandir(directory):
            if entry.is_file():
                files.append({"name": entry.name, "subdir": ""})
                if len(files) >= max_files:
                    return files
    return files


def _normalize_stem(stem: str) -> str:
    cleaned = _COPY_SUFFIX_RE.sub("", stem)
    cleaned = _DATEISH_RE.sub("", cleaned)
    # Preserve internal underscores to keep meaningful grouping signatures.
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    cleaned = cleaned.strip(" -().")
    return cleaned


def _digit_glob_signature(stem: str) -> str:
    norm = _normalize_stem(stem)
    if not norm:
        return ""
    # Convert digit runs to glob class; compatible with current FileRenamer glob semantics.
    sig = _DIGIT_RUN_RE.sub("[0-9]*", norm)
    # Collapse duplicates if repeated.
    while "[0-9]*[0-9]*" in sig:
        sig = sig.replace("[0-9]*[0-9]*", "[0-9]*")
    return sig


def _confidence(count: int, total: int) -> int:
    if total <= 0:
        return 0
    pct = count / total
    return max(1, min(99, int(25 + (pct * 70))))


def _subdir_breakdown(items: list[dict], max_dirs: int = 4) -> list[dict]:
    counts = Counter(i["subdir"] or "." for i in items)
    return [{"subdir": name, "count": count} for name, count in counts.most_common(max_dirs)]


def _build_suggestion(pattern: str, reason: str, files_for_group: list[dict], total_files: int, score: int):
    affected = len(files_for_group)
    pct = round((affected / total_files) * 100, 2) if total_files else 0.0
    return {
        "search_patterns": pattern,
        "reason": reason,
        "score": score,
        "confidence": _confidence(affected, total_files),
        "affected_files": affected,
        "affected_percent": pct,
        "subdirs": _subdir_breakdown(files_for_group),
    }


def _matching_files_for_pattern(files: list[dict], pattern: str) -> list[dict]:
    """
    Match using the same broad semantics as FileRenamer:
    user pattern is effectively expanded to pattern + "*".
    """
    glob_like = f"{pattern}*"
    matched = []
    for item in files:
        stem = os.path.splitext(item["name"])[0]
        if fnmatch.fnmatch(stem, glob_like):
            matched.append(item)
    return matched


def _expand_signature_candidates(sig: str) -> set[str]:
    """
    Produce a signature and a few broader parent candidates so we can
    surface less-restrictive patterns (e.g. [0-9]*x_auto__ from ...__so).
    """
    candidates = {sig}

    # Heuristic: if suffix is after a double underscore, include parent.
    if "__" in sig:
        idx = sig.rfind("__")
        if idx >= 0:
            parent = sig[: idx + 2]
            if parent and parent != sig:
                candidates.add(parent)

    # Also include parent up to last single underscore boundary.
    if "_" in sig:
        idx = sig.rfind("_")
        if idx > 0:
            parent = sig[: idx + 1]
            if parent and parent != sig:
                candidates.add(parent)

    return {c for c in candidates if c.strip()}


def suggest_renamer_rules(directory: str, recursive: bool = False, max_rules: int = 12) -> list[dict]:
    """
    Suggest renamer mapping rules by inspecting filename patterns.

    Notes:
    - Suggestions are sorted by confidence + score.
    - search_patterns are generated to be glob-compatible with FileRenamer.
    """
    files = _iter_files(directory, recursive=recursive)
    if not files:
        return []

    total = len(files)
    stems = [os.path.splitext(f["name"])[0] for f in files]
    ext_counts = Counter(os.path.splitext(f["name"])[1].lower() for f in files)

    suggestions = []

    # 1) Structural signatures with numeric wildcards (e.g. [0-9]*x_auto__)
    signature_groups = defaultdict(list)
    for file_item, stem in zip(files, stems):
        sig = _digit_glob_signature(stem)
        if not sig:
            continue
        signature_groups[sig].append(file_item)

    seen_structural = set()
    for sig in signature_groups.keys():
        for candidate in _expand_signature_candidates(sig):
            if candidate in seen_structural:
                continue
            seen_structural.add(candidate)
            if len(candidate.replace("[0-9]*", "").strip("_- ")) < 3:
                continue
            matched = _matching_files_for_pattern(files, candidate)
            count = len(matched)
            if count < 3:
                continue
            suggestions.append(
                _build_suggestion(
                    pattern=candidate,
                    reason=f"Structural glob candidate matching {count} file(s).",
                    files_for_group=matched,
                    total_files=total,
                    score=count * 8,
                )
            )

    # 2) Common leading token prefixes.
    token_groups = defaultdict(list)
    for file_item, stem in zip(files, stems):
        normalized = _normalize_stem(stem)
        parts = [p.lower() for p in _SEPARATOR_RE.split(normalized) if p]
        if not parts:
            continue
        token = parts[0]
        if token in _STOPWORDS or len(token) < 3:
            continue
        token_groups[token].append(file_item)

    for token, group_items in token_groups.items():
        count = len(group_items)
        if count < 3:
            continue
        matched = _matching_files_for_pattern(files, token)
        if len(matched) < 3:
            continue
        suggestions.append(
            _build_suggestion(
                pattern=token,
                reason=f"Common leading token in {count} file(s).",
                files_for_group=matched,
                total_files=total,
                score=count * 5,
            )
        )

    # 3) Detect hex-looking names.
    hex_files = [f for f, stem in zip(files, stems) if _HEX_RE.search(stem)]
    if len(hex_files) >= 2:
        matched = _matching_files_for_pattern(files, "{{sixty_four_uppercase_hexadecimal}}")
        if not matched:
            matched = hex_files
        suggestions.append(
            _build_suggestion(
                pattern="{{sixty_four_uppercase_hexadecimal}}",
                reason=f"Detected long hexadecimal patterns in {len(hex_files)} file(s).",
                files_for_group=matched,
                total_files=total,
                score=len(hex_files) * 6,
            )
        )

    # 4) Dominant extension bucket (lower confidence, still useful).
    if ext_counts:
        ext, ext_count = ext_counts.most_common(1)[0]
        if ext and ext_count >= 4:
            ext_files = [f for f in files if os.path.splitext(f["name"])[1].lower() == ext]
            suggestions.append(
                _build_suggestion(
                    pattern=ext,
                    reason=f"Extension {ext} appears in {ext_count} file(s).",
                    files_for_group=ext_files,
                    total_files=total,
                    score=ext_count,
                )
            )

    # Deduplicate by pattern/tag pair and sort by confidence then score.
    seen = set()
    deduped = []
    ordered = sorted(suggestions, key=lambda s: (s["confidence"], s["score"], s["affected_files"]), reverse=True)
    for item in ordered:
        key = str(item["search_patterns"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max_rules:
            break
    return deduped
