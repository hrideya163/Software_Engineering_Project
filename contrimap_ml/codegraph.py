"""Repository code graph: import resolution, knowledge graph, analytics and views.

The knowledge graph (``networkx.DiGraph``) has typed nodes and edges:

    repository -contains-> directory -contains-> file
    file -imports-> file            (resolved per language)
    test file -tests-> file         (imports or naming convention)
    repository -uses-> package      (dependency manifests)
    repository -has_skill-> skill
    issue -affects-> file           (predicted localization, weighted)
    issue -requires-> skill
    contributor -touched-> file / -has_skill-> skill

Analytics: PageRank over the import graph (core files), Louvain communities
(architectural modules), approximate betweenness (bridging files) and reverse
reachability (impact radius of a change).
"""

from __future__ import annotations

import json
import math
import posixpath
import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import networkx as nx

from .corpus import EXTENSION_LANGUAGE, is_test_path

SOURCE_EXTENSIONS = set(EXTENSION_LANGUAGE)
MANIFESTS = {"package.json", "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Cargo.toml", "go.mod", "Gemfile", "composer.json", "pom.xml", "build.gradle", "build.gradle.kts", "Pipfile", "environment.yml"}
_JS_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".d.ts"]
# Only parenthesised import lists may span lines; otherwise `[\s]` would swallow the next statement.
_PY_IMPORT = re.compile(r"^[ \t]*(?:from[ \t]+(\.*[\w.]*)[ \t]+import[ \t]+(\([^)]*\)|[\w*, \t]+)|import[ \t]+([\w., \t]+))", re.M)
_JS_IMPORT = re.compile(r"""(?:import\s+(?:[\w*{}\s,$]+\s+from\s+)?|export\s+[\w*{}\s,$]+\s+from\s+|require\(\s*|import\(\s*)["'`]([^"'`]+)["'`]""")
_GO_IMPORT_BLOCK = re.compile(r"import\s*\(([^)]*)\)", re.S)
_GO_IMPORT_LINE = re.compile(r'import\s+(?:\w+\s+)?"([^"]+)"')
_RUST_MOD = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;", re.M)
_RUST_USE = re.compile(r"^\s*(?:pub\s+)?use\s+(crate|super|self)((?:::\w+)+)", re.M)
_JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;?", re.M)
_C_INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.M)
_RUBY_REQUIRE = re.compile(r"""^\s*require(_relative)?\s+["']([^"']+)["']""", re.M)
_PHP_USE = re.compile(r"^\s*use\s+([\w\\]+)", re.M)


def is_manifest(path: str) -> bool:
    """Root manifests plus first-level packages of monorepos; examples/docs/tests are ignored."""
    parts = path.split("/")
    if PurePosixPath(path).name not in MANIFESTS or len(parts) > 3:
        return False
    return not any(re.match(r"(examples?|docs?|tests?|fixtures?|benchmarks?|samples?|demo)$", part, re.I) for part in parts[:-1])


def is_source(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in SOURCE_EXTENSIONS


def select_content_paths(files: Sequence[str], limit: int = 1500, priority: Iterable[str] = ()) -> list[str]:
    """Which files to download for import parsing: manifests, priority files, then shallow sources."""
    priority = [path for path in priority if path in set(files)]
    manifests = [path for path in files if is_manifest(path)]
    sources = sorted((path for path in files if is_source(path)), key=lambda path: (is_test_path(path), path.count("/"), len(path)))
    chosen = list(dict.fromkeys(manifests + priority + sources))
    return chosen[:limit]


# ---------------------------------------------------------------------------
# Import resolution
# ---------------------------------------------------------------------------
class ImportResolver:
    def __init__(self, files: Sequence[str], contents: Mapping[str, str]):
        self.files = list(files)
        self.file_set = set(files)
        self.contents = contents
        self.python_modules: dict[str, str] = {}
        self.suffix_index: defaultdict[str, list[str]] = defaultdict(list)
        self.dir_files: defaultdict[str, list[str]] = defaultdict(list)
        for path in files:
            self.dir_files[posixpath.dirname(path)].append(path)
            parts = path.split("/")
            for length in range(1, min(5, len(parts)) + 1):
                self.suffix_index["/".join(parts[-length:])].append(path)
            if path.endswith(".py"):
                module = path[:-3].replace("/", ".")
                module = module[: -len(".__init__")] if module.endswith(".__init__") else module
                self.python_modules.setdefault(module, path)
                for prefix in ("src.", "lib.", "python."):
                    if module.startswith(prefix):
                        self.python_modules.setdefault(module[len(prefix):], path)
        self.go_module = ""
        for path, content in contents.items():
            if PurePosixPath(path).name == "go.mod":
                match = re.search(r"^module\s+(\S+)", content, re.M)
                if match:
                    self.go_module = match.group(1)
                    break

    def _by_suffix(self, suffix: str) -> str | None:
        hits = self.suffix_index.get(suffix.strip("/"))
        return min(hits, key=len) if hits else None

    def _python(self, path: str, content: str) -> set[str]:
        targets: set[str] = set()
        package = posixpath.dirname(path).replace("/", ".")
        for source, names, plain in _PY_IMPORT.findall(content):
            if plain:
                modules = [name.split(" as ")[0].strip() for name in plain.split(",")]
            else:
                dots = len(source) - len(source.lstrip("."))
                base = source.lstrip(".")
                if dots:
                    anchor = package.split(".") if package else []
                    anchor = anchor[: len(anchor) - (dots - 1)] if dots > 1 else anchor
                    base = ".".join(part for part in [*anchor, base] if part)
                imported = [name.strip(" ()").split(" as ")[0].strip() for name in names.split(",")]
                modules = [f"{base}.{name}" for name in imported if name and name != "*"] + [base]
            for module in modules:
                parts = module.split(".")
                for end in range(len(parts), 0, -1):
                    hit = self.python_modules.get(".".join(parts[:end]))
                    if hit:
                        targets.add(hit)
                        break
        return targets

    def _js(self, path: str, content: str) -> set[str]:
        targets: set[str] = set()
        for spec in _JS_IMPORT.findall(content):
            if spec.startswith("."):
                base = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
            elif spec.startswith(("@/", "~/")):
                base = "src/" + spec[2:]
            else:
                continue
            candidates = [base] + [base + ext for ext in _JS_EXTENSIONS] + [f"{base}/index{ext}" for ext in _JS_EXTENSIONS]
            hit = next((candidate for candidate in candidates if candidate in self.file_set), None)
            if hit:
                targets.add(hit)
        return targets

    def _go(self, path: str, content: str) -> set[str]:
        specs = _GO_IMPORT_LINE.findall(content)
        for block in _GO_IMPORT_BLOCK.findall(content):
            specs += re.findall(r'"([^"]+)"', block)
        targets: set[str] = set()
        for spec in specs:
            if self.go_module and spec.startswith(self.go_module):
                directory = spec[len(self.go_module):].strip("/")
                for file in self.dir_files.get(directory, [])[:8]:
                    if file.endswith(".go") and not file.endswith("_test.go"):
                        targets.add(file)
        return targets

    def _rust(self, path: str, content: str) -> set[str]:
        targets: set[str] = set()
        directory = posixpath.dirname(path)
        if not PurePosixPath(path).name in {"mod.rs", "lib.rs", "main.rs"}:
            directory = posixpath.join(directory, PurePosixPath(path).stem)
        for module in _RUST_MOD.findall(content):
            for candidate in (f"{directory}/{module}.rs", f"{directory}/{module}/mod.rs"):
                if candidate in self.file_set:
                    targets.add(candidate)
        crate_root = path.split("/src/")[0] + "/src" if "/src/" in path else "src"
        for anchor, rest in _RUST_USE.findall(content):
            parts = [part for part in rest.split("::") if part]
            root = crate_root if anchor == "crate" else posixpath.dirname(path)
            for end in range(len(parts), 0, -1):
                stem = posixpath.join(root, *parts[:end])
                hit = next((candidate for candidate in (stem + ".rs", stem + "/mod.rs") if candidate in self.file_set), None)
                if hit:
                    targets.add(hit)
                    break
        return targets

    def _java(self, path: str, content: str, extension: str) -> set[str]:
        targets: set[str] = set()
        for spec in _JAVA_IMPORT.findall(content):
            parts = spec.split(".")
            for end in range(len(parts), 1, -1):
                hit = self._by_suffix("/".join(parts[:end]) + extension)
                if hit:
                    targets.add(hit)
                    break
        return targets

    def _c(self, path: str, content: str) -> set[str]:
        targets: set[str] = set()
        for spec in _C_INCLUDE.findall(content):
            local = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
            hit = local if local in self.file_set else self._by_suffix(spec)
            if hit:
                targets.add(hit)
        return targets

    def _ruby(self, path: str, content: str) -> set[str]:
        targets: set[str] = set()
        for relative, spec in _RUBY_REQUIRE.findall(content):
            spec = spec if spec.endswith(".rb") else spec + ".rb"
            candidate = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec)) if relative else f"lib/{spec}"
            hit = candidate if candidate in self.file_set else (None if relative else self._by_suffix(spec))
            if hit:
                targets.add(hit)
        return targets

    def _php(self, path: str, content: str) -> set[str]:
        targets: set[str] = set()
        for spec in _PHP_USE.findall(content):
            parts = spec.split("\\")
            for start in range(len(parts) - 1):
                hit = self._by_suffix("/".join(parts[start:]) + ".php")
                if hit:
                    targets.add(hit)
                    break
        return targets

    def resolve(self, path: str) -> set[str]:
        content = self.contents.get(path) or ""
        if not content:
            return set()
        extension = PurePosixPath(path).suffix.lower()
        if extension in {".py", ".pyx"}:
            found = self._python(path, content)
        elif extension in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"}:
            found = self._js(path, content)
        elif extension == ".go":
            found = self._go(path, content)
        elif extension == ".rs":
            found = self._rust(path, content)
        elif extension in {".java", ".kt"}:
            found = self._java(path, content, extension) | self._java(path, content, ".kt" if extension == ".java" else ".java")
        elif extension in {".c", ".h", ".cc", ".cpp", ".hpp", ".cxx"}:
            found = self._c(path, content)
        elif extension == ".rb":
            found = self._ruby(path, content)
        elif extension == ".php":
            found = self._php(path, content)
        else:
            found = set()
        found.discard(path)
        return found


def import_edges(files: Sequence[str], contents: Mapping[str, str]) -> list[tuple[str, str]]:
    resolver = ImportResolver(files, contents)
    return [(path, target) for path in contents if is_source(path) for target in sorted(resolver.resolve(path))]


def test_edges(files: Sequence[str], imports: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """test -> source links from imports, else from naming (test_foo.py / foo.test.ts / FooTest.java)."""
    edges = {(source, target) for source, target in imports if is_test_path(source) and not is_test_path(target)}
    tested = {source for source, _ in edges}
    by_stem: defaultdict[str, list[str]] = defaultdict(list)
    for path in files:
        if is_source(path) and not is_test_path(path):
            by_stem[PurePosixPath(path).stem.lower()].append(path)
    for path in files:
        if not is_test_path(path) or not is_source(path) or path in tested:
            continue
        stem = PurePosixPath(path).stem.lower()
        stem = re.sub(r"^test_|_test$|\.test$|\.spec$|_spec$|tests?$", "", stem)
        for target in by_stem.get(stem, [])[:2]:
            edges.add((path, target))
    return sorted(edges)


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------
def build_repository_graph(snapshot: Mapping[str, Any]) -> nx.DiGraph:
    """Knowledge graph from a v2 snapshot (see ``snapshot.build_git_snapshot``)."""
    graph = nx.DiGraph()
    repo = str(snapshot.get("full_name") or "repository")
    graph.add_node(repo, kind="repository", label=repo)
    for path in snapshot.get("files") or []:
        parent = repo
        parts = path.split("/")
        for depth in range(1, len(parts)):
            directory = "/".join(parts[:depth])
            if directory not in graph:
                graph.add_node(directory, kind="directory", label=parts[depth - 1] + "/", depth=depth)
                graph.add_edge(parent, directory, type="contains")
            parent = directory
        graph.add_node(path, kind="file", label=parts[-1], language=EXTENSION_LANGUAGE.get(PurePosixPath(path).suffix.lower()), is_test=is_test_path(path), depth=len(parts))
        graph.add_edge(parent, path, type="contains")
    for source, target in snapshot.get("import_edges") or []:
        if source in graph and target in graph:
            graph.add_edge(source, target, type="imports")
    for source, target in snapshot.get("test_edges") or []:
        if source in graph and target in graph:
            graph.add_edge(source, target, type="tests")
    for package in snapshot.get("packages") or []:
        node = f"pkg:{package}"
        graph.add_node(node, kind="package", label=package)
        graph.add_edge(repo, node, type="uses")
    for skill in snapshot.get("skills") or []:
        node = f"skill:{skill['id']}"
        graph.add_node(node, kind="skill", label=skill["name"], weight=skill["weight"])
        graph.add_edge(repo, node, type="has_skill", weight=skill["weight"])
    return graph


def add_issue(graph: nx.DiGraph, issue_id: str, title: str, files: Sequence[Mapping[str, Any]], skills: Iterable[Mapping[str, Any]] = ()) -> None:
    node = f"issue:{issue_id}"
    graph.add_node(node, kind="issue", label=f"#{issue_id}", title=title)
    for item in files:
        if item["path"] in graph:
            graph.add_edge(node, item["path"], type="affects", weight=float(item.get("relative_confidence") or 0.0), rank=item.get("rank"))
    for skill in skills:
        skill_node = f"skill:{skill['id']}"
        graph.add_node(skill_node, kind="skill", label=skill["name"])
        graph.add_edge(node, skill_node, type="requires", weight=float(skill.get("weight", 0.0)))


def add_contributor(graph: nx.DiGraph, login: str, files: Mapping[str, int], skills: Iterable[Mapping[str, Any]] = ()) -> None:
    node = f"user:{login}"
    graph.add_node(node, kind="contributor", label=login)
    for path, count in files.items():
        if path in graph:
            graph.add_edge(node, path, type="touched", weight=float(count))
    for skill in skills:
        skill_node = f"skill:{skill['id']}"
        graph.add_node(skill_node, kind="skill", label=skill["name"])
        graph.add_edge(node, skill_node, type="has_skill", weight=float(skill.get("weight", 0.0)))


def import_subgraph(graph: nx.DiGraph) -> nx.DiGraph:
    return nx.DiGraph([(u, v) for u, v, data in graph.edges(data=True) if data.get("type") == "imports"])


def graph_metrics(graph: nx.DiGraph, seed: int = 7) -> dict[str, Any]:
    """Per-file PageRank, betweenness and community over the import graph."""
    imports = import_subgraph(graph)
    if imports.number_of_nodes() == 0:
        return {"pagerank": {}, "betweenness": {}, "community": {}, "in_degree": {}, "summary": {"import_edges": 0, "files_with_imports": 0, "communities": 0, "modularity": 0.0, "core_files": []}}
    pagerank = nx.pagerank(imports, alpha=0.85)
    k = min(200, imports.number_of_nodes())
    betweenness = nx.betweenness_centrality(imports, k=k, seed=seed) if imports.number_of_nodes() > 2 else {}
    undirected = imports.to_undirected()
    communities = nx.community.louvain_communities(undirected, seed=seed) if undirected.number_of_edges() else [set(imports.nodes)]
    community = {node: index for index, members in enumerate(sorted(communities, key=len, reverse=True)) for node in members}
    return {
        "pagerank": pagerank,
        "betweenness": betweenness,
        "community": community,
        "in_degree": dict(imports.in_degree()),
        "summary": {
            "import_edges": imports.number_of_edges(),
            "files_with_imports": imports.number_of_nodes(),
            "communities": len(communities),
            "modularity": float(nx.community.modularity(undirected, communities)) if undirected.number_of_edges() else 0.0,
            "core_files": [node for node, _ in sorted(pagerank.items(), key=lambda item: -item[1]) if not is_test_path(node)][:10],
        },
    }


def impact_radius(graph: nx.DiGraph, files: Iterable[str], depth: int = 2) -> dict[str, int]:
    """Files that (transitively) import the given files, with their distance."""
    reverse = import_subgraph(graph).reverse(copy=False)
    found: dict[str, int] = {}
    for start in files:
        if start not in reverse:
            continue
        for node, distance in nx.single_source_shortest_path_length(reverse, start, cutoff=depth).items():
            if distance and (node not in found or distance < found[node]):
                found[node] = distance
    return found


# ---------------------------------------------------------------------------
# Views for the frontend visualizer (@xyflow/react nodes/edges with positions)
# ---------------------------------------------------------------------------
def _directory_of(path: str, depth: int) -> str:
    parts = path.split("/")
    return "/".join(parts[: min(depth, len(parts) - 1)]) or "(root)"


def architecture_view(graph: nx.DiGraph, metrics: Mapping[str, Any], highlight: Sequence[Mapping[str, Any]] = (), max_nodes: int = 30) -> dict[str, Any]:
    """Directory-level architecture map with aggregated import edges and optional issue highlighting."""
    files = [node for node, data in graph.nodes(data=True) if data.get("kind") == "file" and not data.get("is_test")]
    depth = 1
    while depth < 6:
        if len({_directory_of(path, depth + 1) for path in files}) > max_nodes:
            break
        depth += 1
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for path in files:
        groups[_directory_of(path, depth)].append(path)
    pagerank = metrics.get("pagerank") or {}
    # Keep the most important directories if there are still too many.
    ranked = sorted(groups, key=lambda key: -(sum(pagerank.get(path, 0.0) for path in groups[key]) * 1000 + len(groups[key])))[:max_nodes]
    keep = set(ranked)
    highlight_score: defaultdict[str, float] = defaultdict(float)
    for item in highlight:
        directory = _directory_of(str(item["path"]), depth)
        highlight_score[directory] = max(highlight_score[directory], float(item.get("relative_confidence") or 0.0) or 1.0 / (item.get("rank") or 1))
    weights: Counter = Counter()
    for source, target, data in graph.edges(data=True):
        if data.get("type") != "imports":
            continue
        a, b = _directory_of(source, depth), _directory_of(target, depth)
        if a != b and a in keep and b in keep:
            weights[(a, b)] += 1
    # Deterministic layout: one column per top-level directory, most important sub-directories first.
    # (Force layouts scatter sparse import graphs into an unreadable ring.)
    columns: defaultdict[str, list[str]] = defaultdict(list)
    for key in ranked:
        columns[key.split("/")[0]].append(key)
    positions: dict[str, tuple[float, float]] = {}
    order = sorted(columns, key=lambda top: (-len(columns[top]), top))
    per_row = max(1, min(len(order), 6))
    row_offset = 0.0
    for start in range(0, len(order), per_row):
        band = order[start:start + per_row]
        for column, top in enumerate(band):
            for row, key in enumerate(columns[top]):
                positions[key] = (column * 270.0, row_offset + row * 95.0)
        row_offset += max(len(columns[top]) for top in band) * 95.0 + 80.0
    communities = metrics.get("community") or {}
    nodes = []
    for key in ranked:
        members = groups[key]
        languages = Counter(graph.nodes[path].get("language") for path in members if graph.nodes[path].get("language"))
        community = Counter(communities[path] for path in members if path in communities)
        x, y = positions[key]
        nodes.append({
            "id": f"dir:{key}",
            "type": "directory",
            "position": {"x": x, "y": y},
            "data": {
                "label": key if key != "(root)" else "(root)",
                "files": len(members),
                "language": languages.most_common(1)[0][0] if languages else None,
                "importance": round(sum(pagerank.get(path, 0.0) for path in members), 5),
                "community": community.most_common(1)[0][0] if community else None,
                "highlight": round(highlight_score.get(key, 0.0), 4),
                "top_files": sorted(members, key=lambda path: -pagerank.get(path, 0.0))[:5],
            },
        })
    edges = [{"id": f"e:{a}->{b}", "source": f"dir:{a}", "target": f"dir:{b}", "data": {"imports": count}} for (a, b), count in weights.most_common(150)]
    return {"level": "directory", "depth": depth, "nodes": nodes, "edges": edges, "summary": metrics.get("summary", {})}


def issue_view(graph: nx.DiGraph, predicted: Sequence[Mapping[str, Any]], metrics: Mapping[str, Any] | None = None, max_neighbors: int = 6) -> dict[str, Any]:
    """File-level neighbourhood of an issue's predicted files: importers, imports and tests."""
    metrics = metrics or {}
    pagerank = metrics.get("pagerank") or {}
    targets = [item for item in predicted if item["path"] in graph][:6]
    target_paths = {item["path"] for item in targets}
    roles: dict[str, str] = {item["path"]: "target" for item in targets}
    edges: set[tuple[str, str, str]] = set()
    for path in target_paths:
        importers = sorted((u for u, _, d in graph.in_edges(path, data=True) if d.get("type") == "imports"), key=lambda node: -pagerank.get(node, 0.0))[:max_neighbors]
        imported = sorted((v for _, v, d in graph.out_edges(path, data=True) if d.get("type") == "imports"), key=lambda node: -pagerank.get(node, 0.0))[:max_neighbors]
        tests = [u for u, _, d in graph.in_edges(path, data=True) if d.get("type") == "tests"][:3]
        for node in importers:
            roles.setdefault(node, "importer")
            edges.add((node, path, "imports"))
        for node in imported:
            roles.setdefault(node, "dependency")
            edges.add((path, node, "imports"))
        for node in tests:
            roles.setdefault(node, "test")
            edges.add((node, path, "tests"))
    for a in target_paths:
        for b in target_paths:
            if a != b and graph.has_edge(a, b) and graph.edges[a, b].get("type") == "imports":
                edges.add((a, b, "imports"))
    columns = {"importer": 0, "target": 1, "dependency": 2, "test": 1}
    counters: Counter = Counter()
    rank_of = {item["path"]: item.get("rank") for item in targets}
    nodes = []
    for path, role in sorted(roles.items(), key=lambda item: (columns[item[1]], item[1] == "test", rank_of.get(item[0]) or 99, item[0])):
        column = columns[role]
        row = counters[(column, role == "test")]
        counters[(column, role == "test")] += 1
        y = row * 90 + (len(target_paths) * 90 + 60 if role == "test" else 0)
        nodes.append({
            "id": path,
            "type": role,
            "position": {"x": column * 360, "y": y},
            "data": {"label": path.rsplit("/", 1)[-1], "path": path, "role": role, "rank": rank_of.get(path), "importance": round(pagerank.get(path, 0.0), 5)},
        })
    return {
        "level": "file",
        "nodes": nodes,
        "edges": [{"id": f"{a}->{b}:{kind}", "source": a, "target": b, "data": {"type": kind}} for a, b, kind in sorted(edges)],
        "impact": {"dependents_within_2_hops": len(impact_radius(graph, target_paths))},
    }


def file_tree(files: Sequence[str], highlight: Sequence[Mapping[str, Any]] = (), max_children: int = 60) -> dict[str, Any]:
    """Nested directory tree with highlighted (predicted) files and ancestor counts."""
    ranks = {item["path"]: item.get("rank") for item in highlight}
    root: dict[str, Any] = {"name": "", "path": "", "type": "directory", "children": {}, "highlighted": 0}
    for path in files:
        node = root
        parts = path.split("/")
        for depth, part in enumerate(parts):
            is_file = depth == len(parts) - 1
            key = "/".join(parts[: depth + 1])
            child = node["children"].get(part)
            if child is None:
                child = {"name": part, "path": key, "type": "file" if is_file else "directory", "children": {}, "highlighted": 0}
                node["children"][part] = child
            if path in ranks:
                node["highlighted"] += 1
            node = child
        if path in ranks:
            node["rank"] = ranks[path]

    def finalize(node: dict[str, Any]) -> dict[str, Any]:
        children = sorted(node["children"].values(), key=lambda child: (-child["highlighted"] - (1 if child.get("rank") else 0), child["type"] != "directory", child["name"]))
        visible = [child for child in children if child["highlighted"] or child.get("rank")] + [child for child in children if not (child["highlighted"] or child.get("rank"))]
        result = {key: value for key, value in node.items() if key != "children"}
        if node["type"] == "directory":
            result["children"] = [finalize(child) for child in visible[:max_children]]
            result["hidden_children"] = max(0, len(visible) - max_children)
        return result

    return finalize(root)


def to_json(graph: nx.DiGraph) -> dict[str, Any]:
    return json.loads(json.dumps(nx.node_link_data(graph, edges="edges"), default=str))


__all__ = [
    "ImportResolver", "add_contributor", "add_issue", "architecture_view", "build_repository_graph", "file_tree",
    "graph_metrics", "impact_radius", "import_edges", "import_subgraph", "issue_view", "select_content_paths", "test_edges", "to_json",
]
