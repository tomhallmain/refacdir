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
