"""Code-reading features for localization: what the candidate files *contain*.

Stage 1 of localization ranks every file in the repository from its path,
the issue text and the repository's history.  It cannot tell that the
``parse_header()`` named in an issue is defined in ``utils/http.py``.  This
module reads the contents of the stage-1 shortlist (top ~50 files) and scores
them against the issue:

* ``code_def_hits`` / ``code_def_idf`` - identifiers named in the issue that the
  file *defines* (functions, classes, methods, types, constants), weighted by
  how few shortlisted files define the same name;
* ``code_ref_hits`` - identifiers named in the issue that the file merely uses;
* ``code_string_hit`` - quoted strings / error messages from the issue that
  occur literally in the file (an error message is usually raised where it is
  written);
* ``code_bm25`` / ``code_def_bm25`` - BM25 of the issue against the file's
  identifier tokens and against its definition names only;
* ``code_lines`` / ``code_n_defs`` / ``code_missing`` - size, and whether the
  content could be read.

Only file contents at the issue's base commit are used - the same information
a contributor has when they start - so there is no label leakage.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from typing import NamedTuple, Mapping, Sequence

import numpy as np

from .textfeat import extract_mentions, split_identifier, text_tokens

CODE_FEATURES = [
    "code_def_hits", "code_def_idf", "code_ref_hits", "code_string_hit", "code_bm25", "code_bm25_rel",
    "code_def_bm25", "code_lines", "code_n_defs", "code_missing",
]

_DEFINITION_PATTERNS = [
    # Python, Ruby, Go, Rust, Kotlin, Swift, Scala, PHP, JS function declarations.
    re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:def|fn|func|fun|function)\s+(?:\([^)]*\)\s*)?(?:self\.)?([A-Za-z_]\w*)", re.M),
    # Classes, structs, interfaces, traits, enums, modules, type aliases.
    re.compile(r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:(?:public|private|protected|internal|abstract|final|sealed|static|data|open)\s+)*(?:class|struct|interface|trait|enum|module|type|record|object|union)\s+([A-Za-z_]\w*)", re.M),
    # JS/TS bindings: const foo = (...) => / const Foo = class / export const BAR =
    re.compile(r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*[:=]", re.M),
    # Module-level constants (Python / C macros).
    re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*[:=]", re.M),
    re.compile(r"^[ \t]*#\s*define\s+([A-Za-z_]\w*)", re.M),
    # Methods in JS/TS/Java/C#/C++ classes: `  name(args) {` or `public Foo bar(args) {`.
    re.compile(r"^[ \t]+(?:(?:public|private|protected|static|final|async|override|virtual|get|set|synchronized)\s+)*(?:[\w<>\[\],.?]+\s+)?([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:[\w\s,.<>]*)\{", re.M),
    # C/C++ functions at column 0: `int foo(...)` followed by `{` on the same or next line.
    re.compile(r"^[A-Za-z_][\w\s\*&:<>,]*?\b([A-Za-z_]\w*)\s*\([^;]*\)\s*(?:const\s*)?\n?\{", re.M),
]
_KEYWORDS = {
    "if", "for", "while", "switch", "return", "catch", "function", "new", "else", "elif", "with", "match", "sizeof",
    "typeof", "await", "yield", "super", "this", "self", "constructor", "init", "main",
}
_QUOTED = re.compile(r"""(?<![\w])["'`]([^"'`\n]{8,160})["'`]""")
_EXCEPTION_LINE = re.compile(r"^\s*(?:[\w.]+(?:Error|Exception|Warning)|panic|error|fatal)(?::|\s-)\s*(.{8,160})$", re.M | re.I)
_BM25_K1, _BM25_B = 1.2, 0.75


def definitions(content: str) -> set[str]:
    """Names of functions, classes, methods, types and constants defined in ``content``."""
    names: set[str] = set()
    for pattern in _DEFINITION_PATTERNS:
        names.update(match for match in pattern.findall(content) if match not in _KEYWORDS and len(match) > 2)
    return names


def issue_symbols(text: str) -> set[str]:
    """Code identifiers named in an issue: snake/camel identifiers, calls, dotted-path parts, backticked words."""
    mentions = extract_mentions(text)
    symbols = set(mentions["identifiers"])
    for dotted in mentions["dotted"]:
        symbols.update(part for part in dotted.split(".") if len(part) > 2)
    symbols.update(word for word in re.findall(r"`([A-Za-z_]\w{2,})`", text))
    return {symbol for symbol in symbols if symbol not in _KEYWORDS and len(symbol) > 2 and not symbol.isdigit()}


def issue_strings(text: str) -> list[str]:
    """Literal strings worth searching for in code: quoted text and exception messages."""
    found = {match.strip() for match in _QUOTED.findall(text)}
    found |= {match.strip().rstrip(".") for match in _EXCEPTION_LINE.findall(text)}
    # Drop strings that are mostly placeholders or file paths; keep the distinctive ones.
    return [value for value in found if len(value) >= 8 and " " in value and "/" not in value][:40]


class _ContentIndex(NamedTuple):
    """Everything code_features needs from one file, computed once per distinct content."""

    defs: frozenset
    tokens: tuple
    lines: int
    identifiers: frozenset
    lowered: str
    counter: Counter
    def_counter: Counter
    length: int
    def_length: int


@lru_cache(maxsize=4096)
def _content_index(content: str) -> _ContentIndex:
    head = content[:200_000]
    defs = frozenset(definitions(content))
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", head)
    tokens = tuple(token for word in words for token in split_identifier(word) if len(token) > 1)
    def_tokens = [token for name in defs for token in split_identifier(name)]
    return _ContentIndex(defs, tokens, content.count("\n") + 1, frozenset(words), head.lower(), Counter(tokens), Counter(def_tokens), len(tokens), len(def_tokens))


_EMPTY = _ContentIndex(frozenset(), (), 0, frozenset(), "", Counter(), Counter(), 0, 0)


def _content_summary(content: str) -> tuple[frozenset[str], tuple[str, ...], int]:
    index = _content_index(content)
    return index.defs, index.tokens, index.lines


def _bm25(query: Counter[str], documents: Sequence[Sequence[str]], counters: Sequence[Counter] | None = None, lengths: Sequence[int] | None = None) -> np.ndarray:
    n = len(documents) if counters is None else len(counters)
    scores = np.zeros(n, dtype="float32")
    if not n or not query:
        return scores
    lengths = np.asarray([len(doc) for doc in documents] if lengths is None else lengths, dtype="float32")
    average = float(lengths.mean()) or 1.0
    counters = [Counter(doc) for doc in documents] if counters is None else counters
    for token, query_tf in query.items():
        df = sum(1 for counter in counters if token in counter)
        if not df:
            continue
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        weight = idf * (1 + math.log(query_tf))
        for index, counter in enumerate(counters):
            tf = counter.get(token)
            if tf:
                scores[index] += weight * tf * (_BM25_K1 + 1) / (tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * lengths[index] / average))
    return scores


def code_features(text: str, candidates: Sequence[str], contents: Mapping[str, str]) -> np.ndarray:
    """Return an ``(n_candidates, len(CODE_FEATURES))`` matrix for the shortlisted ``candidates``."""
    n = len(candidates)
    matrix = np.zeros((n, len(CODE_FEATURES)), dtype="float32")
    if not n:
        return matrix
    column = {name: index for index, name in enumerate(CODE_FEATURES)}
    symbols = issue_symbols(text)
    lowered_symbols = {symbol.lower(): symbol for symbol in symbols}
    strings = [value.lower() for value in issue_strings(text)]
    query = Counter(text_tokens(text))

    indexes = [_content_index(contents[path]) if contents.get(path) else _EMPTY for path in candidates]
    # How many shortlisted files define each symbol: a name defined everywhere (``__init__``, ``get``) is weak evidence.
    define_count: Counter[str] = Counter()
    for index in indexes:
        define_count.update(name.lower() for name in index.defs if name.lower() in lowered_symbols)

    for row, path in enumerate(candidates):
        index = indexes[row]
        if not contents.get(path):
            matrix[row, column["code_missing"]] = 1.0
            continue
        lowered_defs = {name.lower() for name in index.defs}
        hits = [symbol for symbol in lowered_symbols if symbol in lowered_defs]
        matrix[row, column["code_def_hits"]] = math.log1p(len(hits))
        matrix[row, column["code_def_idf"]] = sum(math.log(1 + n / define_count[symbol]) for symbol in hits)
        matrix[row, column["code_ref_hits"]] = math.log1p(sum(1 for symbol in symbols if symbol in index.identifiers))
        matrix[row, column["code_string_hit"]] = float(sum(1 for value in strings if value in index.lowered))
        matrix[row, column["code_lines"]] = math.log1p(index.lines)
        matrix[row, column["code_n_defs"]] = math.log1p(len(index.defs))

    bm25 = _bm25(query, (), [index.counter for index in indexes], [index.length for index in indexes])
    matrix[:, column["code_bm25"]] = bm25
    matrix[:, column["code_bm25_rel"]] = bm25 / bm25.max() if bm25.max() > 0 else 0.0
    matrix[:, column["code_def_bm25"]] = _bm25(query, (), [index.def_counter for index in indexes], [index.def_length for index in indexes])
    return matrix


__all__ = ["CODE_FEATURES", "code_features", "definitions", "issue_strings", "issue_symbols"]
