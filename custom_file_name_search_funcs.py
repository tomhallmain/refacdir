import math
import os
import random
import re
from collections import Counter

from refacdir.utils.persistent_pattern_cache import persistent_cache


# Add any custom filename search functions here to gather files for the BatchRenamers as set in the config YAML.


_VOWELS = frozenset('aeiouAEIOU')
_HEX_CHARS = frozenset('0123456789abcdefABCDEF')


def _get_runs(s):
    """Split s into consecutive (class, substring) runs; class is 'alpha', 'digit', or 'other'."""
    if not s:
        return []
    runs = []
    cls = 'digit' if s[0].isdigit() else ('alpha' if s[0].isalpha() else 'other')
    start = 0
    for i in range(1, len(s)):
        c = s[i]
        new_cls = 'digit' if c.isdigit() else ('alpha' if c.isalpha() else 'other')
        if new_cls != cls:
            runs.append((cls, s[start:i]))
            cls = new_cls
            start = i
    runs.append((cls, s[start:]))
    return runs


def _shannon_entropy(s):
    """Per-character Shannon entropy of s in bits."""
    if not s:
        return 0.0
    n = len(s)
    return -sum((count / n) * math.log2(count / n) for count in Counter(s).values())


def any_file(filename):
    return True


def random_selection(filename, chance=0.5):
    return random.random() <= chance


def is_short_integer_filename(filename, max_length=5):
    """True if the basename (minus extension) is purely digits, 1-max_length chars long."""
    file_basename = os.path.basename(filename)
    filename_part = file_basename.split(".")[0] if "." in file_basename else file_basename
    return filename_part.isdigit() and 1 <= len(filename_part) <= max_length


@persistent_cache
def is_id_filename(filename, fixed_length=22):
    file_basename = os.path.basename(filename)
    filename_part = file_basename.split(".")[0] if "." in file_basename else file_basename
    return is_id(filename_part, fixed_length=fixed_length)


@persistent_cache
def is_id(s, min_length=6, fixed_length=None):
    """
    Determine if a string appears to be a randomized ID rather than a human-chosen name.

    Uses a tiered approach, working from strongest to weakest evidence:

    Tier 1 — alpha-digit-alpha interleaving within a segment.
    A digit group sandwiched directly between alpha characters (no separator in between)
    is incompatible with every common naming convention: words don't embed digits in
    their interior, camelCase words don't, and "word_number_word" patterns separate the
    digit with underscores or dashes. This catches short strings like "ab3f6d" that the
    old mixed-case requirement would miss entirely.  The signal is suppressed only when
    both neighbouring alpha groups are long (> 3 chars), because then they likely are
    whole words — e.g. "backup2023final" — rather than fragments of a random ID.

    Also fires when three or more distinct digit groups appear anywhere in the string;
    structured names very rarely use more than one or two separate numeric sections.

    Tier 2 — pure hex fast-path.
    Strings whose separator-stripped form consists entirely of [0-9a-fA-F], has at
    least 8 characters, and contains at least one alpha hex character.  This catches
    hash fragments and UUID-style IDs that are all lowercase (and so would be missed
    by the old mixed-case requirement).

    Tier 3 — entropy and structural heuristics (stripped length >= 10 only).
    Applied when tiers 1 and 2 are not conclusive:
      - Vowel ratio > 40 % among alpha chars indicates natural-language content.
      - Shannon entropy below a length-dependent threshold indicates patterned/structured
        content rather than random content.
      - A max alpha run > 5 chars suggests a dictionary word is present.
      - Mixed case surviving all of the above is taken as a positive signal.
    """
    if not s:
        return False

    length = len(s)

    # Exact-length contract — checked first since it's an external caller constraint.
    if fixed_length is not None and length != fixed_length:
        return False

    # Character set gate — only alphanumeric plus dash and underscore separators
    if not re.match(r'^[A-Za-z0-9_-]+$', s):
        return False

    # Split on separators so that "word_123_word" (three distinct separated segments)
    # is not confused with the within-segment interleaving of "ab3f6d".
    segments = [seg for seg in re.split(r'[_-]+', s) if seg]

    # -------------------------------------------------------------------------
    # Tier 1: alpha-digit-alpha interleaving
    # Applied before the min_length gate — this signal is strong enough to
    # identify IDs at very short lengths (e.g. "x9y").
    # -------------------------------------------------------------------------
    total_digit_groups = 0
    for seg in segments:
        runs = _get_runs(seg)
        total_digit_groups += sum(1 for cls, _ in runs if cls == 'digit')

        for i, (cls, _) in enumerate(runs):
            if cls != 'digit':
                continue
            left_alpha = i > 0 and runs[i - 1][0] == 'alpha'
            right_alpha = i < len(runs) - 1 and runs[i + 1][0] == 'alpha'

            if left_alpha and right_alpha:
                left_len = len(runs[i - 1][1])
                right_len = len(runs[i + 1][1])
                # Suppress only when BOTH neighbours are long enough to be whole words;
                # one short neighbour (≤ 3 chars) is enough to rule out word+number+word.
                if left_len > 3 and right_len > 3:
                    continue
                return True

    # Three or more distinct digit groups is also a reliable indicator; structured
    # names (dates, versions, sequential numbers) rarely use more than two.
    if total_digit_groups >= 3:
        return True

    # Min-length gate — applied after Tier 1 so the strong interleaving signal
    # can still fire on short strings.
    if length < min_length:
        return False

    # -------------------------------------------------------------------------
    # Tier 2: pure hex fast-path
    # -------------------------------------------------------------------------
    core = s.replace('-', '').replace('_', '')
    core_len = len(core)

    if (core_len >= 8
            and all(c in _HEX_CHARS for c in core)
            and any(c.isalpha() for c in core)):
        return True

    # -------------------------------------------------------------------------
    # Tier 3: entropy and structural heuristics (longer strings only)
    # -------------------------------------------------------------------------
    if core_len < 10:
        return False

    # High vowel ratio among alpha chars → likely contains natural-language words.
    # Random [A-Za-z0-9] strings average ~18 % vowels; English text averages ~38 %.
    alpha_chars = [c for c in core if c.isalpha()]
    if alpha_chars:
        vowel_ratio = sum(1 for c in alpha_chars if c in _VOWELS) / len(alpha_chars)
        if vowel_ratio > 0.40:
            return False

    # Low Shannon entropy → repetitive or structured content, not random.
    # Random alphanumeric from a 62-char alphabet approaches log2(62) ≈ 5.95 bits/char;
    # human-readable names fall well below that.  The threshold is relaxed for shorter
    # strings where the frequency estimate is less reliable.
    entropy = _shannon_entropy(core)
    entropy_threshold = 3.2 if core_len < 14 else 3.8
    if entropy < entropy_threshold:
        return False

    # Mixed case with a high upper/lower transition density is a reliable positive signal
    # even for pure-alpha strings (e.g. "RkQmTvXnPwLz") that have no digit interleaving.
    # Word-boundary case changes (camelCase, PascalCase) produce a low rate (~0.2-0.4);
    # truly random case mixing produces one close to 1.0.
    has_upper = any(c.isupper() for c in core)
    has_lower = any(c.islower() for c in core)
    if has_upper and has_lower:
        alpha_adj = [(core[i], core[i + 1]) for i in range(len(core) - 1)
                     if core[i].isalpha() and core[i + 1].isalpha()]
        if alpha_adj:
            uc_transitions = sum(1 for a, b in alpha_adj if a.isupper() != b.isupper())
            if uc_transitions / len(alpha_adj) > 0.5:
                return True

    # Long unbroken alpha run suggests a dictionary word is present.
    # Checked after the transition-density test so that dense-transition pure-alpha
    # strings are not incorrectly killed here.
    runs = _get_runs(core)
    max_alpha_run = max((len(val) for cls, val in runs if cls == 'alpha'), default=0)
    if max_alpha_run > 5:
        return False

    # Mixed case surviving all of the above is still a positive signal.
    if has_upper and has_lower:
        return True

    return False
