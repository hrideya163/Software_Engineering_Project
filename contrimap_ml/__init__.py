"""Supervised ML pipeline for ContriMap contribution intelligence."""

from .explanation import generate_explanation
from .graph_features import GRAPH_FEATURE_COLUMNS, graph_aware_features
from .knowledge_graph import build_knowledge_graph, load_knowledge_graph, save_knowledge_graph
from .mining import NormalizedMiningRecord, normalize_record, normalize_snapshot
from .models import ContriMapModels, train_models
from .ranking import rank_candidates, rank_repository_items
from .snapshot import RepositorySnapshot, build_snapshot, build_snapshot_from_directory, load_snapshot, save_snapshot

__all__ = [
    "ContriMapModels",
    "GRAPH_FEATURE_COLUMNS",
    "NormalizedMiningRecord",
    "RepositorySnapshot",
    "build_knowledge_graph",
    "build_snapshot",
    "build_snapshot_from_directory",
    "generate_explanation",
    "graph_aware_features",
    "load_knowledge_graph",
    "load_snapshot",
    "normalize_record",
    "normalize_snapshot",
    "rank_candidates",
    "rank_repository_items",
    "save_knowledge_graph",
    "save_snapshot",
    "train_models",
]
