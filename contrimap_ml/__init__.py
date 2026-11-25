"""ContriMap contribution-intelligence package.

Exports are resolved lazily so that importing a light submodule (for example
``contrimap_ml.repo_trees``) does not load torch / sentence-transformers.
"""

import os
from importlib import import_module

# sentence-transformers would otherwise import TensorFlow when it is installed (slow, noisy).
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

_EXPORTS = {
    "generate_explanation": ".explanation",
    "is_valid_candidate": ".features",
    "deduplicate_dataset": ".features",
    "GRAPH_FEATURE_COLUMNS": ".graph_features",
    "graph_aware_features": ".graph_features",
    "graph_aware_features_safe": ".graph_features",
    "GitHubInferenceError": ".inference",
    "analyzeIssue": ".inference",
    "fetchRepositoryIssues": ".inference",
    "load_models": ".inference",
    "build_knowledge_graph": ".knowledge_graph",
    "load_knowledge_graph": ".knowledge_graph",
    "save_knowledge_graph": ".knowledge_graph",
    "NormalizedMiningRecord": ".mining",
    "normalize_record": ".mining",
    "normalize_snapshot": ".mining",
    "ContriMapModels": ".models",
    "train_models": ".models",
    "rank_candidates": ".ranking",
    "rank_repository_items": ".ranking",
    "RepositorySnapshot": ".snapshot",
    "build_snapshot": ".snapshot",
    "build_snapshot_from_directory": ".snapshot",
    "load_snapshot": ".snapshot",
    "save_snapshot": ".snapshot",
    "ContriMapPredictor": ".predictor",
    "load_predictor": ".predictor",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    if name in _EXPORTS:
        return getattr(import_module(_EXPORTS[name], __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
