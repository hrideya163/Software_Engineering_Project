from __future__ import annotations

import re
import logging

import networkx as nx
import pandas as pd

logger = logging.getLogger(__name__)

GRAPH_FEATURE_COLUMNS = [
    "graph_in_degree",
    "graph_out_degree",
    "graph_total_degree",
    "graph_pagerank",
    "graph_betweenness",
    "graph_closeness",
]


def _extract_file_mentions(text: str) -> list[str]:
    """Extract plausible file paths mentioned in issue title/body.

    This uses text-only information available at inference time,
    NOT the actual changed_files (which are post-hoc labels).
    """
    # Match patterns like path/to/file.ext or file.ext
    candidates = re.findall(r'[a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9]{1,10}', text)
    # Filter to plausible paths (at least one path separator or common extension)
    result = []
    for c in candidates:
        c = c.replace("\\", "/").strip("./")
        if not c or len(c) < 3:
            continue
        # Must look like a file path (has extension)
        if "/" in c or any(c.endswith(ext) for ext in [".js", ".ts", ".py", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".md", ".css", ".html"]):
            result.append(c)
    return result


def graph_aware_features_safe(frame: pd.DataFrame, graph: nx.Graph | None = None) -> pd.DataFrame:
    """Compute graph features using ONLY issue text mentions, NOT changed_files.

    This prevents target leakage: at inference time we only have the issue
    title and body, not the actual files that will be changed.
    """
    if graph is None or frame.empty:
        return pd.DataFrame(index=frame.index)

    try:
        pagerank = nx.pagerank(graph, weight="weight") if graph.number_of_edges() else {node: 0.0 for node in graph.nodes}
        betweenness = nx.betweenness_centrality(graph, weight="weight") if graph.number_of_edges() else {node: 0.0 for node in graph.nodes}
        closeness = nx.closeness_centrality(graph) if graph.number_of_nodes() > 1 else {node: 0.0 for node in graph.nodes}
    except Exception as e:
        logger.warning("Failed to compute graph centrality metrics: %s", e)
        return pd.DataFrame(
            [{name: 0.0 for name in GRAPH_FEATURE_COLUMNS}] * len(frame),
            index=frame.index,
            columns=GRAPH_FEATURE_COLUMNS,
        )

    rows: list[dict[str, float]] = []
    for _, row in frame.iterrows():
        # Use ONLY text-derived file mentions, not changed_files
        text = f"{row.get('issue_title', '')} {row.get('issue_body', '')}"
        mentioned = _extract_file_mentions(text)

        node_scores = []
        for item in mentioned:
            if item in graph:
                node_scores.append({
                    "in_degree": graph.in_degree(item) if hasattr(graph, "in_degree") else graph.degree(item),
                    "out_degree": graph.out_degree(item) if hasattr(graph, "out_degree") else graph.degree(item),
                    "pagerank": pagerank.get(item, 0.0),
                    "betweenness": betweenness.get(item, 0.0),
                    "closeness": closeness.get(item, 0.0),
                })
        if not node_scores:
            rows.append({name: 0.0 for name in GRAPH_FEATURE_COLUMNS})
            continue
        rows.append({
            "graph_in_degree": sum(item["in_degree"] for item in node_scores),
            "graph_out_degree": sum(item["out_degree"] for item in node_scores),
            "graph_total_degree": sum(item["in_degree"] + item["out_degree"] for item in node_scores),
            "graph_pagerank": sum(item["pagerank"] for item in node_scores),
            "graph_betweenness": sum(item["betweenness"] for item in node_scores),
            "graph_closeness": sum(item["closeness"] for item in node_scores),
        })
    return pd.DataFrame(rows, index=frame.index, columns=GRAPH_FEATURE_COLUMNS)


# Keep the original function available for backward compat but mark it
def graph_aware_features(frame: pd.DataFrame, graph: nx.Graph | None = None) -> pd.DataFrame:
    """Backward-compatible alias. Delegates to the safe version."""
    return graph_aware_features_safe(frame, graph)


__all__ = ["GRAPH_FEATURE_COLUMNS", "graph_aware_features", "graph_aware_features_safe"]
