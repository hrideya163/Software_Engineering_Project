from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import networkx as nx


def build_knowledge_graph(snapshot: Mapping[str, Any]) -> nx.DiGraph:
    graph = nx.DiGraph()
    repository = snapshot.get("repository") or {}
    repository_name = repository.get("name") or repository.get("full_name") or "repository"
    graph.add_node(repository_name, kind="repository", name=repository_name)

    for file in snapshot.get("files") or []:
        path = str(file.get("path") or file.get("name") or "")
        if not path:
            continue
        graph.add_node(path, kind="file", path=path, language=file.get("language"), content=file.get("content", ""))
        graph.add_edge(repository_name, path, type="contains", weight=1.0)

    for edge in snapshot.get("dependencyEdges") or snapshot.get("dependency_edges") or []:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source and target:
            graph.add_edge(source, target, type="imports", weight=1.0)

    pull_requests = snapshot.get("pullRequests") or snapshot.get("pull_requests") or []
    for module in snapshot.get("modules") or []:
        module_name = str(module)
        graph.add_node(module_name, kind="module", name=module_name)
        for file_node, attrs in list(graph.nodes(data=True)):
            if attrs.get("kind") == "file" and str(file_node).startswith(module_name + "/"):
                graph.add_edge(file_node, module_name, type="belongs_to_module", weight=1.0)
    for dependency in snapshot.get("dependency_packages") or []:
        dependency_name = str(dependency)
        graph.add_node(dependency_name, kind="dependency", name=dependency_name)
        graph.add_edge(repository_name, dependency_name, type="uses_dependency", weight=1.0)

    for issue in snapshot.get("issues") or []:
        issue_id = str(issue.get("id") or issue.get("number") or "issue")
        graph.add_node(issue_id, kind="issue", title=issue.get("title") or "", body=issue.get("body") or "")
        graph.add_edge(repository_name, issue_id, type="tracks", weight=1.0)
        for file_path in issue.get("changed_files") or issue.get("files") or []:
            path = str(file_path.get("filename") if isinstance(file_path, Mapping) else file_path)
            if path:
                graph.add_edge(issue_id, path, type="affects_file", weight=1.0)
        for label in issue.get("labels") or []:
            label_name = str(label)
            graph.add_node(label_name, kind="label", name=label_name)
            graph.add_edge(issue_id, label_name, type="tagged_with", weight=1.0)

    for pr in pull_requests:
        pr_id = str(pr.get("id") or pr.get("number") or "pull_request")
        graph.add_node(pr_id, kind="pull_request", title=pr.get("title") or "", body=pr.get("body") or "")
        graph.add_edge(repository_name, pr_id, type="contains", weight=1.0)
        for file in pr.get("files") or []:
            file_path = str(file.get("path") or file.get("name") or "")
            if file_path:
                graph.add_edge(pr_id, file_path, type="changes", weight=1.0)
        for issue_id in pr.get("linked_issue_numbers") or pr.get("linked_issues") or []:
            graph.add_edge(str(issue_id), pr_id, type="resolved_by", weight=1.0)

    for contributor in snapshot.get("contributors") or []:
        contributor_name = str(contributor)
        graph.add_node(contributor_name, kind="contributor", name=contributor_name)
        graph.add_edge(repository_name, contributor_name, type="has_contributor", weight=1.0)

    return graph


def save_knowledge_graph(graph: nx.Graph, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "nodes": [{"id": node, **attrs} for node, attrs in graph.nodes(data=True)],
        "edges": [{"source": source, "target": target_node, **attrs} for source, target_node, attrs in graph.edges(data=True)],
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def load_knowledge_graph(path: str | Path) -> nx.DiGraph:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    graph = nx.DiGraph()
    for node in payload.get("nodes") or []:
        graph.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})
    for edge in payload.get("edges") or []:
        graph.add_edge(edge["source"], edge["target"], **{k: v for k, v in edge.items() if k not in {"source", "target"}})
    return graph


__all__ = ["build_knowledge_graph", "save_knowledge_graph", "load_knowledge_graph"]
