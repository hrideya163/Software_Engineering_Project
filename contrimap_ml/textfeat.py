"""Issue-text processing shared by every model: tokens, mentions, features, embeddings.

Only information present when an issue is opened is used here.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Iterable

import numpy as np

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

logger = logging.getLogger(__name__)

EMBEDDER_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_CACHE = Path(__file__).resolve().parent.parent / "data" / "processed" / "embeddings"
_MODELS: dict[str, object] = {}

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_PATH_LIKE = re.compile(r"(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,8}|[\w-]+\.(?:py|pyx|js|jsx|mjs|ts|tsx|go|rs|java|kt|rb|php|c|h|cc|cpp|hpp|cs|swift|scala|vue|svelte|json|ya?ml|toml|md|rst|cfg|ini|html|css|scss|sh)\b")
_DOTTED = re.compile(r"\b[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){1,6}\b")
_IDENTIFIER = re.compile(r"\b(?:[a-z]+(?:_[a-z0-9]+)+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+|[a-z]+[A-Z][A-Za-z0-9]*)\b")
_CALL = re.compile(r"\b([A-Za-z_][\w]*)\s*\(")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "for", "on", "with", "this", "that", "be", "as", "are",
    "was", "but", "not", "if", "when", "from", "by", "at", "i", "we", "you", "can", "should", "would", "will", "have",
    "has", "do", "does", "there", "my", "so", "use", "using", "used", "py", "js", "ts", "src", "lib", "get", "set", "self",
}

HANDCRAFTED_COLUMNS = [
    "title_chars", "body_chars", "body_lines", "code_blocks", "inline_code", "has_traceback", "path_mentions",
    "identifier_mentions", "url_count", "has_repro", "has_expected", "version_mentions", "question_marks",
    "label_count", "label_good_first_issue", "label_bug", "label_feature", "label_docs", "label_help_wanted",
    "label_performance", "label_security", "label_breaking", "title_is_question", "title_docs", "title_typo",
    "title_feature", "title_bug", "title_refactor", "list_items",
]


def split_identifier(token: str) -> list[str]:
    parts: list[str] = []
    for piece in re.split(r"[_\-./\\]+", token):
        parts.extend(part.lower() for part in _CAMEL.split(piece) if part)
    return parts


def text_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for word in _WORD.findall(text or ""):
        lowered = word.lower()
        if lowered not in _STOP and len(lowered) > 1:
            tokens.append(lowered)
        if any(ch.isupper() for ch in word[1:]) or "_" in word:
            tokens.extend(part for part in split_identifier(word) if part not in _STOP and len(part) > 1)
    return tokens


def path_tokens(path: str) -> list[str]:
    stem_path = re.sub(r"\.[A-Za-z0-9]+$", "", path)
    return [token for token in split_identifier(stem_path) if token and token not in _STOP]


def path_text(path: str) -> str:
    """Natural-language rendering of a path for sentence embeddings."""
    return " ".join(path_tokens(path)) + " " + path


def extract_mentions(text: str) -> dict[str, set[str]]:
    """Paths, dotted module names, identifiers and called symbols mentioned in issue text."""
    text = text or ""
    paths = {match.replace("\\", "/").lstrip("./") for match in _PATH_LIKE.findall(text)}
    # Traceback paths: File "/site-packages/pkg/mod.py", line 3
    paths |= {match.replace("\\", "/") for match in re.findall(r'File "([^"]+)"', text)}
    dotted = {match for match in _DOTTED.findall(text) if not re.search(r"\.(com|org|io|net|html?|md)$", match)}
    identifiers = set(_IDENTIFIER.findall(text)) | {match for match in _CALL.findall(text) if len(match) > 2}
    return {"paths": paths, "dotted": dotted, "identifiers": identifiers}


def handcrafted_features(title: str, body: str, labels: Iterable[str] = ()) -> dict[str, float]:
    title, body = title or "", body or ""
    lowered_labels = [str(label).lower() for label in labels]
    lowered_title = title.lower()
    mentions = extract_mentions(f"{title}\n{body}")

    def has_label(*needles: str) -> float:
        return float(any(needle in label for label in lowered_labels for needle in needles))

    return {
        "title_chars": float(len(title)),
        "body_chars": float(np.log1p(len(body))),
        "body_lines": float(np.log1p(body.count("\n"))),
        "code_blocks": float(body.count("```") // 2),
        "inline_code": float(np.log1p(len(re.findall(r"`[^`\n]+`", body)))),
        "has_traceback": float("Traceback (most recent call last)" in body or bool(re.search(r"^\s+at .+\(.+:\d+:\d+\)", body, re.M)) or "panicked at" in body),
        "path_mentions": float(len(mentions["paths"])),
        "identifier_mentions": float(np.log1p(len(mentions["identifiers"]))),
        "url_count": float(len(re.findall(r"https?://", body))),
        "has_repro": float(bool(re.search(r"(steps to reproduce|reproduc|minimal example|mcve|to reproduce)", body, re.I))),
        "has_expected": float(bool(re.search(r"expected (behaviou?r|result|output)", body, re.I))),
        "version_mentions": float(len(re.findall(r"\bv?\d+\.\d+(?:\.\d+)?\b", body))),
        "question_marks": float(body.count("?")),
        "label_count": float(len(lowered_labels)),
        "label_good_first_issue": has_label("good first", "beginner", "starter", "easy"),
        "label_bug": has_label("bug", "defect", "regression"),
        "label_feature": has_label("feature", "enhancement"),
        "label_docs": has_label("doc"),
        "label_help_wanted": has_label("help wanted"),
        "label_performance": has_label("perf"),
        "label_security": has_label("security"),
        "label_breaking": has_label("breaking"),
        "title_is_question": float(lowered_title.strip().endswith("?") or lowered_title.startswith(("how", "why", "what", "is there"))),
        "title_docs": float(bool(re.search(r"\b(doc|docs|documentation|docstring|readme)\b", lowered_title))),
        "title_typo": float(bool(re.search(r"\b(typo|spelling|grammar|wording)\b", lowered_title))),
        "title_feature": float(bool(re.search(r"\b(add|support|feature|allow|enable|new|implement)\b", lowered_title))),
        "title_bug": float(bool(re.search(r"\b(bug|error|fail|fails|crash|broken|wrong|incorrect|exception|regression)\b", lowered_title))),
        "title_refactor": float(bool(re.search(r"\b(refactor|deprecat|rename|cleanup|clean up|migrate)\b", lowered_title))),
        "list_items": float(np.log1p(len(re.findall(r"^\s*(?:[-*]|\d+\.)\s+", body, re.M)))),
    }


def get_embedder(name: str = EMBEDDER_NAME):
    if name not in _MODELS:
        from sentence_transformers import SentenceTransformer

        device = os.getenv("CONTRIMAP_DEVICE")
        if device is None:
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
        _MODELS[name] = SentenceTransformer(name, device=device)
    return _MODELS[name]


def embed(texts: list[str], name: str = EMBEDDER_NAME, batch_size: int = 128, cache: bool = True) -> np.ndarray:
    """Unit-normalized embeddings; large batches are cached on disk by content hash."""
    if not texts:
        return np.zeros((0, 384), dtype="float32")
    texts = [(text or " ")[:2000] for text in texts]
    key = None
    if cache and len(texts) >= 256:
        digest = hashlib.sha1(("\x00".join(texts) + name).encode("utf-8", "replace")).hexdigest()[:16]
        key = EMBED_CACHE / f"{digest}.npy"
        if key.exists():
            return np.load(key)
    vectors = np.asarray(get_embedder(name).encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False), dtype="float32")
    if key is not None:
        key.parent.mkdir(parents=True, exist_ok=True)
        np.save(key, vectors)
    return vectors


__all__ = ["EMBEDDER_NAME", "HANDCRAFTED_COLUMNS", "embed", "extract_mentions", "get_embedder", "handcrafted_features", "path_text", "path_tokens", "split_identifier", "text_tokens"]
