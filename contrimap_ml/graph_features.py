from __future__ import annotations

import networkx as nx
import pandas as pd

GRAPH_FEATURE_COLUMNS = [
    "graph_in_degree",
    "graph_out_degree",
    "graph_total_degree",
    "graph_pagerank",
    "graph_betweenness",
    "graph_closeness",
]


def graph_aware_features(frame: pd.DataFrame, graph: nx.Graph | None = None) -> pd.DataFrame:
    if graph is None or frame.empty:
        return pd.DataFrame(index=frame.index)
    pagerank = nx.pagerank(graph, weight="weight") if graph.number_of_edges() else {node: 0.0 for node in graph.nodes}
    betweenness = nx.betweenness_centrality(graph, weight="weight") if graph.number_of_edges() else {node: 0.0 for node in graph.nodes}
    closeness = nx.closeness_centrality(graph) if graph.number_of_nodes() > 1 else {node: 0.0 for node in graph.nodes}
    rows: list[dict[str, float]] = []
    for _, row in frame.iterrows():
        changed = [str(item) for item in row.get("changed_files") or []]
        if not changed:
            text = str(row.get("issue_title") or row.get("issue_body") or "")
            changed = [segment for segment in text.split() if "." in segment or "/" in segment]
        node_scores = []
        for item in changed:
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


__all__ = ["GRAPH_FEATURE_COLUMNS", "graph_aware_features"]
