"""File-level and module-level views for the repository visualizer.

* :func:`extract_symbols` lists the functions and classes a source file defines (regex per language).
* :func:`symbol_usage` finds which of those names each importing file references (name-level, not type-checked).
* :func:`file_details` gathers a file's imports, dependents, tests and graph metrics.
* :func:`module_view` expands one directory of the architecture map into its files, laid out in layers.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

import networkx as nx

_SYMBOL_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "python": [("class", re.compile(r"^class\s+([A-Za-z_]\w*)", re.M)), ("function", re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)", re.M)), ("method", re.compile(r"^[ \t]+(?:async\s+)?def\s+([A-Za-z_]\w*)", re.M))],
    "javascript": [
        ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", re.M)),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)", re.M)),
        ("function", re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", re.M)),
        ("type", re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)", re.M)),
    ],
    "go": [("function", re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)", re.M)), ("type", re.compile(r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)", re.M))],
    "rust": [("function", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)", re.M)), ("type", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)", re.M))],
    "java": [("class", re.compile(r"^\s*(?:public|protected|private|abstract|final|static|\s)*\s*(?:class|interface|enum|record)\s+([A-Za-z_]\w*)", re.M)), ("method", re.compile(r"^\s+(?:public|protected|private)\s+(?:static\s+)?(?:final\s+)?[\w<>\[\], ]+\s+([a-z_]\w*)\s*\(", re.M))],
    "ruby": [("class", re.compile(r"^\s*(?:class|module)\s+([A-Z]\w*)", re.M)), ("method", re.compile(r"^\s*def\s+(?:self\.)?([a-z_]\w*[?!]?)", re.M))],
    "php": [("class", re.compile(r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait)\s+([A-Za-z_]\w*)", re.M)), ("function", re.compile(r"function\s+([A-Za-z_]\w*)\s*\(", re.M))],
    "c": [("function", re.compile(r"^[A-Za-z_][\w \t\*]*?\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", re.M)), ("type", re.compile(r"^\s*(?:typedef\s+)?(?:struct|class|enum)\s+([A-Za-z_]\w*)\s*[{:]", re.M))],
}
_FAMILY = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "javascript", ".tsx": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".vue": "javascript", ".svelte": "javascript",
           ".go": "go", ".rs": "rust", ".java": "java", ".kt": "java", ".scala": "java", ".rb": "ruby", ".php": "php", ".c": "c", ".h": "c", ".cc": "c", ".cpp": "c", ".hpp": "c", ".cs": "java"}
_KEYWORDS = {"if", "for", "while", "switch", "return", "catch", "sizeof", "else", "main"}


def extract_symbols(path: str, content: str, limit: int = 80) -> list[dict[str, Any]]:
    """Functions, classes and types defined in ``content`` with 1-based line numbers, in file order."""
    family = _FAMILY.get(PurePosixPath(path).suffix.lower())
    if not family or not content:
        return []
    line_starts = [0] + [match.end() for match in re.finditer(r"\n", content)]
    found: dict[str, dict[str, Any]] = {}
    for kind, pattern in _SYMBOL_PATTERNS[family]:
        for match in pattern.finditer(content):
            name = match.group(1)
            if name in _KEYWORDS or name in found:
                continue
            line = _line_of(line_starts, match.start(1))
            found[name] = {"name": name, "kind": kind, "line": line, "private": name.startswith("_") and not name.startswith("__")}
    return sorted(found.values(), key=lambda symbol: symbol["line"])[:limit]


def _line_of(line_starts: Sequence[int], offset: int) -> int:
    import bisect

    return bisect.bisect_right(line_starts, offset)


def symbol_usage(symbols: Sequence[Mapping[str, Any]], importers: Mapping[str, str], limit: int = 12) -> list[dict[str, Any]]:
    """For each importing file, the defined names it references (word match outside the import line too)."""
    names = [symbol["name"] for symbol in symbols if not symbol.get("private") and not symbol["name"].startswith("__") and len(symbol["name"]) > 3]
    if not names:
        return []
    pattern = re.compile(r"\b(" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + r")\b")
    usage = []
    for path, content in importers.items():
        counts = Counter(pattern.findall(content or ""))
        if counts:
            usage.append({"path": path, "symbols": [name for name, _ in counts.most_common(8)], "references": sum(counts.values())})
    usage.sort(key=lambda item: -item["references"])
    return usage[:limit]


def symbol_dependents(usage: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Invert :func:`symbol_usage`: for each name, the files that use it (most used first)."""
    users: defaultdict[str, list[str]] = defaultdict(list)
    for item in usage:
        for name in item["symbols"]:
            users[name].append(item["path"])
    return [{"name": name, "used_by": paths} for name, paths in sorted(users.items(), key=lambda entry: -len(entry[1]))]


def file_details(graph: nx.DiGraph, metrics: Mapping[str, Any], path: str, limit: int = 15) -> dict[str, Any]:
    if path not in graph or graph.nodes[path].get("kind") != "file":
        raise KeyError(path)
    pagerank = metrics.get("pagerank") or {}
    data = graph.nodes[path]
    by_importance = lambda nodes: sorted(nodes, key=lambda node: -pagerank.get(node, 0.0))  # noqa: E731
    imports = by_importance([v for _, v, d in graph.out_edges(path, data=True) if d.get("type") == "imports"])
    dependents = by_importance([u for u, _, d in graph.in_edges(path, data=True) if d.get("type") == "imports"])
    tests = sorted({u for u, _, d in graph.in_edges(path, data=True) if d.get("type") == "tests"})
    ranks = sorted(pagerank.values(), reverse=True)
    score = pagerank.get(path, 0.0)
    percentile = 1.0 - (ranks.index(score) / max(len(ranks), 1)) if score in ranks else 0.0
    return {
        "path": path,
        "language": data.get("language"),
        "is_test": bool(data.get("is_test")),
        "importance": round(score, 6),
        "importance_percentile": round(percentile, 3),
        "community": (metrics.get("community") or {}).get(path),
        "imports": imports[:limit],
        "imports_total": len(imports),
        "dependents": dependents[:limit],
        "dependents_total": len(dependents),
        "tests": tests[:limit],
    }


def module_view(graph: nx.DiGraph, metrics: Mapping[str, Any], directory: str, highlight: Sequence[Mapping[str, Any]] = (), include_tests: bool = False, max_nodes: int = 40, rows_per_column: int = 6) -> dict[str, Any]:
    """Files inside ``directory`` (recursively), their import edges and the outside directories they talk to.

    Layout is layered: files that nothing else in the module imports sit on the left, the files they depend on
    to the right (longest path over the import DAG after collapsing cycles), so arrows mostly flow left to right.
    """
    prefix = directory.rstrip("/") + "/" if directory not in ("", "(root)") else ""
    pagerank = metrics.get("pagerank") or {}
    members = [node for node, data in graph.nodes(data=True) if data.get("kind") == "file" and node.startswith(prefix) and (include_tests or not data.get("is_test"))]
    if directory == "(root)":
        members = [node for node in members if "/" not in node]
    members = sorted(members, key=lambda node: -pagerank.get(node, 0.0))
    total = len(members)
    members = members[:max_nodes]
    inside = set(members)
    highlight_rank = {str(item["path"]): item.get("rank") for item in highlight}
    internal: set[tuple[str, str, str]] = set()
    external: Counter = Counter()
    external_dirs: dict[str, str] = {}
    for path in members:
        for _, target, data in graph.out_edges(path, data=True):
            kind = data.get("type")
            if kind not in ("imports", "tests"):
                continue
            if target in inside:
                internal.add((path, target, kind))
            elif kind == "imports" and graph.nodes[target].get("kind") == "file" and not target.startswith(prefix):
                outside = _top_dir(target)
                external[("out", outside)] += 1
                external_dirs[outside] = outside
        for source, _, data in graph.in_edges(path, data=True):
            if data.get("type") == "imports" and source not in inside and graph.nodes[source].get("kind") == "file" and not source.startswith(prefix):
                outside = _top_dir(source)
                external[("in", outside)] += 1
                external_dirs[outside] = outside
    layer = _layers(members, [(a, b) for a, b, kind in internal if kind == "imports"])
    by_layer: defaultdict[int, list[str]] = defaultdict(list)
    for path in members:
        by_layer[layer[path]].append(path)
    # Tall layers (import cycles collapse into one) wrap into side-by-side sub-columns of at most ``rows_per_column``.
    positions: dict[str, tuple[float, float]] = {}
    x = 290.0
    for _, paths in sorted(by_layer.items()):
        ordered = sorted(paths, key=lambda node: (-pagerank.get(node, 0.0), node))
        for index, path in enumerate(ordered):
            positions[path] = (x + (index // rows_per_column) * 260.0, (index % rows_per_column) * 92.0)
        x += ((len(ordered) - 1) // rows_per_column + 1) * 260.0 + 80.0
    max_importance = max([pagerank.get(path, 0.0) for path in members] or [0.0]) or 1.0
    communities = metrics.get("community") or {}
    nodes = [{
        "id": path, "type": "test" if graph.nodes[path].get("is_test") else ("target" if path in highlight_rank else "module_file"),
        "position": {"x": positions[path][0], "y": positions[path][1]},
        "data": {"label": path[len(prefix):] if prefix else path, "path": path, "rank": highlight_rank.get(path), "importance": round(pagerank.get(path, 0.0), 6),
                 "importance_share": round(pagerank.get(path, 0.0) / max_importance, 4), "community": communities.get(path), "language": graph.nodes[path].get("language")},
    } for path in members]
    edges = [{"id": f"{a}->{b}:{kind}", "source": a, "target": b, "data": {"type": kind}} for a, b, kind in sorted(internal)]
    # Outside directories: importers on the far left, dependencies on the far right.
    rightmost = x + 40.0
    rows = Counter()
    for (direction, outside), count in sorted(external.items(), key=lambda item: -item[1])[:16]:
        node_id = f"ext:{direction}:{outside}"
        x = 0.0 if direction == "in" else rightmost
        nodes.append({"id": node_id, "type": "external", "position": {"x": x, "y": rows[direction] * 80.0}, "data": {"label": outside, "path": outside, "direction": direction, "imports": count}})
        rows[direction] += 1
        anchor = members[0] if members else None
        if anchor:
            edges.append({"id": f"{node_id}-agg", "source": node_id if direction == "in" else anchor, "target": anchor if direction == "in" else node_id, "data": {"type": "external", "imports": count}})
    return {"level": "module", "directory": directory, "nodes": nodes, "edges": edges, "files_total": total, "files_shown": len(members), "layers": len(by_layer)}


def _top_dir(path: str) -> str:
    return path.split("/")[0] + "/" if "/" in path else "(root)"


def _layers(nodes: Sequence[str], edges: Sequence[tuple[str, str]]) -> dict[str, int]:
    """Longest-path layering: a file sits one layer left of the files it imports (cycles share a layer)."""
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes)
    graph.add_edges_from(edges)
    condensed = nx.condensation(graph)
    depth: dict[int, int] = {}
    for component in reversed(list(nx.topological_sort(condensed))):
        successors = list(condensed.successors(component))
        depth[component] = 0 if not successors else 1 + max(depth[s] for s in successors)
    longest = max(depth.values(), default=0)
    mapping = condensed.graph["mapping"]
    return {node: longest - depth[mapping[node]] for node in nodes}


__all__ = ["extract_symbols", "file_details", "module_view", "symbol_dependents", "symbol_usage"]
