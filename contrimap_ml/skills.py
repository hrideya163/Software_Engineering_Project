"""Skill extraction and skill matching.

A transparent taxonomy (languages, frameworks/libraries, domains, practices)
is matched against four evidence sources, every hit keeping its evidence:

* issue text      - keyword/alias patterns in title, body and labels;
* file paths      - extensions and path conventions of (predicted) files;
* repository stack - dependency manifests and the language mix of the tree;
* contributor history - files and titles of their merged contributions, or the
  languages/topics of their public repositories.

Skill vectors map ``skill id -> weight in [0, 1]``; matching is weighted
coverage of the issue's needs by the contributor's proficiencies.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping

from .corpus import EXTENSION_LANGUAGE, is_test_path


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    category: str  # language | framework | domain | practice
    text: str = ""  # regex over issue/PR text
    path: str = ""  # regex over file paths
    packages: tuple[str, ...] = ()  # dependency names in manifests
    prerequisites: tuple[str, ...] = ()


def _s(id: str, name: str, category: str, text: str = "", path: str = "", packages: Iterable[str] = (), prerequisites: Iterable[str] = ()) -> Skill:
    return Skill(id, name, category, text, path, tuple(packages), tuple(prerequisites))


TAXONOMY: list[Skill] = [
    # Languages (path evidence comes from EXTENSION_LANGUAGE).
    _s("python", "Python", "language", r"\bpython\b|\bpip\b|\.py\b"),
    _s("javascript", "JavaScript", "language", r"\bjavascript\b|\bnode(\.js)?\b|\bnpm\b|\.js\b"),
    _s("typescript", "TypeScript", "language", r"\btypescript\b|\btsc\b|\.tsx?\b|\btsconfig\b", prerequisites=["javascript"]),
    _s("go", "Go", "language", r"\bgolang\b|\bgo (mod|build|test)\b|\.go\b"),
    _s("rust", "Rust", "language", r"\brust\b|\bcargo\b|\.rs\b|\bborrow checker\b"),
    _s("java", "Java", "language", r"\bjava\b|\bjvm\b|\bmaven\b|\bgradle\b|\.java\b"),
    _s("kotlin", "Kotlin", "language", r"\bkotlin\b|\.kt\b"),
    _s("ruby", "Ruby", "language", r"\bruby\b|\bgem\b|\bbundler\b|\.rb\b"),
    _s("php", "PHP", "language", r"\bphp\b|\bcomposer\b|\.php\b"),
    _s("c", "C", "language", r"\bC language\b|\bsegfault\b|\bmalloc\b|\.c\b|\.h\b"),
    _s("cpp", "C++", "language", r"\bc\+\+|\bcpp\b|\btemplate<|\.cpp\b|\.hpp\b"),
    _s("csharp", "C#", "language", r"\bc#|\.net\b|\bdotnet\b|\.cs\b"),
    _s("swift", "Swift", "language", r"\bswift\b|\.swift\b"),
    _s("shell", "Shell scripting", "language", r"\bbash\b|\bshell script\b|\bzsh\b", r"\.(sh|bash|zsh)$"),
    _s("sql", "SQL", "language", r"\bsql\b|\bselect .+ from\b|\bjoin\b.*\bon\b|\bquery(set)?\b", r"\.sql$"),
    _s("html_css", "HTML & CSS", "language", r"\bcss\b|\bhtml\b|\bscss\b|\bstyles?heet\b|\bflexbox\b", r"\.(css|scss|sass|less|html?)$"),
    # Frameworks / libraries.
    _s("react", "React", "framework", r"\breact\b|\bjsx\b|\buse(State|Effect|Memo|Callback|Ref)\b|\bhooks?\b", r"\.jsx$|\.tsx$", ["react", "react-dom"], ["javascript"]),
    _s("nextjs", "Next.js", "framework", r"\bnext(\.js|js)\b|\bgetServerSideProps\b|\bapp router\b|\bpages router\b", r"(^|/)next\.config\.", ["next"], ["react"]),
    _s("vue", "Vue", "framework", r"\bvue(\.js)?\b|\bnuxt\b", r"\.vue$", ["vue", "nuxt"], ["javascript"]),
    _s("angular", "Angular", "framework", r"\bangular\b", r"\.component\.ts$", ["@angular/core"], ["typescript"]),
    _s("svelte", "Svelte", "framework", r"\bsvelte(kit)?\b", r"\.svelte$", ["svelte"], ["javascript"]),
    _s("node", "Node.js runtime", "framework", r"\bnode(\.js)?\b|\bprocess\.env\b|\bfs\.|\brequire\(", "", ["express", "koa", "fastify"], ["javascript"]),
    _s("express", "Express", "framework", r"\bexpress(js)?\b|\bmiddleware\b", "", ["express"], ["node"]),
    _s("django", "Django", "framework", r"\bdjango\b|\bqueryset\b|\borm\b|\bmigrations?\b", r"(^|/)django/|(^|/)migrations/", ["django"], ["python"]),
    _s("flask", "Flask", "framework", r"\bflask\b|\bblueprint\b|\bwerkzeug\b", "", ["flask"], ["python"]),
    _s("fastapi", "FastAPI", "framework", r"\bfastapi\b|\bpydantic\b|\bstarlette\b", "", ["fastapi", "pydantic"], ["python"]),
    _s("numpy", "NumPy", "framework", r"\bnumpy\b|\bnp\.\w+|\bndarray\b|\bdtype\b|\bbroadcast", "", ["numpy"], ["python"]),
    _s("pandas", "pandas", "framework", r"\bpandas\b|\bdataframe\b|\bpd\.\w+|\bgroupby\b|\bseries\b", r"(^|/)pandas/", ["pandas"], ["numpy"]),
    _s("sklearn", "scikit-learn", "framework", r"\bscikit-learn\b|\bsklearn\b|\bestimator\b|\bfit_transform\b", r"(^|/)sklearn/", ["scikit-learn"], ["numpy"]),
    _s("pytorch", "PyTorch", "framework", r"\bpytorch\b|\btorch\b|\bcuda\b|\btensor\b", "", ["torch"], ["python"]),
    _s("tensorflow", "TensorFlow / JAX", "framework", r"\btensorflow\b|\bkeras\b|\bjax\b|\bxla\b", "", ["tensorflow", "jax"], ["python"]),
    _s("matplotlib", "Matplotlib / plotting", "framework", r"\bmatplotlib\b|\bplt\.\w+|\bfigure\b|\baxes\b|\bseaborn\b|\bcolorbar\b", r"(^|/)(matplotlib|seaborn)/", ["matplotlib", "seaborn"], ["python"]),
    _s("sympy", "SymPy / symbolic math", "framework", r"\bsympy\b|\bsymbolic\b|\bsimplify\b", r"(^|/)sympy/", ["sympy"], ["python"]),
    _s("spring", "Spring", "framework", r"\bspring( boot)?\b|\b@Autowired\b", "", [], ["java"]),
    _s("rails", "Ruby on Rails", "framework", r"\brails\b|\bactiverecord\b", "", ["rails"], ["ruby"]),
    _s("laravel", "Laravel", "framework", r"\blaravel\b|\beloquent\b|\bartisan\b", "", ["laravel/framework"], ["php"]),
    _s("tokio", "Tokio / async Rust", "framework", r"\btokio\b|\basync fn\b|\.await\b", "", ["tokio"], ["rust"]),
    _s("webpack", "Bundlers (webpack/Vite/Rollup)", "framework", r"\bwebpack\b|\bvite\b|\brollup\b|\besbuild\b|\bturbopack\b|\bbundl", r"(webpack|vite|rollup)\.config\.", ["webpack", "vite", "rollup", "esbuild"], ["javascript"]),
    _s("babel", "Babel / transpilers", "framework", r"\bbabel\b|\bswc\b|\btranspil", r"(^|/)(babel|swc)", ["@babel/core"], ["javascript"]),
    _s("graphql", "GraphQL", "framework", r"\bgraphql\b|\bapollo\b", r"\.graphql$", ["graphql"]),
    _s("docker", "Docker", "framework", r"\bdocker(file)?\b|\bcontainer image\b|\bdocker-compose\b", r"(^|/)(Dockerfile|docker-compose\.ya?ml)$"),
    _s("kubernetes", "Kubernetes", "framework", r"\bkubernetes\b|\bk8s\b|\bhelm\b|\bkubectl\b", r"(^|/)(charts|helm|k8s)/"),
    _s("terraform", "Terraform / IaC", "framework", r"\bterraform\b|\bhcl\b", r"\.tf$"),
    # Domains.
    _s("testing", "Testing", "practice", r"\btests?\b|\bpytest\b|\bjest\b|\bunit ?test|\bfixture|\bmock|\bassert|\bflaky|\bcoverage\b", r"(^|/)(tests?|__tests__|spec)/|_test\.|\.test\.|test_", ["pytest", "jest", "mocha", "vitest"]),
    _s("documentation", "Documentation", "practice", r"\bdocs?\b|\bdocumentation\b|\bdocstring\b|\breadme\b|\btypo\b|\bexample\b", r"(^|/)docs?/|\.(md|rst|mdx)$"),
    _s("ci_cd", "CI/CD", "practice", r"\bci\b|\bgithub actions?\b|\bworkflow\b|\bpipeline\b|\btravis\b|\bcircleci\b", r"(^|/)\.github/workflows/|\.gitlab-ci|(^|/)\.circleci/"),
    _s("build_packaging", "Build & packaging", "domain", r"\bbuild\b|\bpackag|\bsetup\.py\b|\bwheel\b|\binstall(ation)?\b|\bdependenc|\bversion(ing)?\b|\bmeson\b|\bcmake\b", r"(setup\.(py|cfg)|pyproject\.toml|package\.json|Cargo\.toml|go\.mod|CMakeLists\.txt|meson\.build|Makefile)$"),
    _s("performance", "Performance optimisation", "domain", r"\bperformance\b|\bslow\b|\bfaster\b|\blatency\b|\bmemory (leak|usage)\b|\bprofil|\bbenchmark|\boptimi[sz]"),
    _s("security", "Security", "domain", r"\bsecurity\b|\bvulnerab|\bcve-|\bxss\b|\bcsrf\b|\binjection\b|\bauth(entication|orization)?\b|\btls\b|\bcrypt", r"(^|/)(auth|security|crypto)"),
    _s("accessibility", "Accessibility", "domain", r"\baccessib|\ba11y\b|\baria-|\bscreen reader\b"),
    _s("i18n", "Internationalisation", "domain", r"\bi18n\b|\bl10n\b|\blocali[sz]|\btranslat|\bunicode\b|\bencoding\b|\butf-?8\b", r"(^|/)(locale|i18n|translations)/|\.po$"),
    _s("ui", "UI / front-end", "domain", r"\bui\b|\bcomponent\b|\brender(ing)?\b|\blayout\b|\bstyl|\bbutton\b|\bmodal\b|\bdark mode\b|\bbrowser\b", r"(^|/)(components?|ui|styles?)/"),
    _s("api_design", "API design", "domain", r"\bapi\b|\bendpoint\b|\brest\b|\bdeprecat|\bbackward[s]? compat|\bsignature\b|\bkeyword argument\b|\bparameter\b", r"(^|/)api/"),
    _s("databases", "Databases", "domain", r"\bdatabase\b|\bpostgres|\bmysql\b|\bsqlite\b|\bredis\b|\bmongo|\bindex(es)?\b|\btransaction\b", r"(^|/)(db|database|migrations)/", ["psycopg2", "sqlalchemy", "redis", "mongodb"]),
    _s("networking", "Networking / HTTP", "domain", r"\bhttps? (request|response|client|server|status)|\bhttp/[12]|\bproxy\b|\bsocket\b|\bhttp headers?\b|\bcookies?\b|\bssl\b|\bwebsocket\b|\bcors\b|\burllib|\brequests library\b", r"(^|/)(http|net|network|client|server)"),
    _s("concurrency", "Concurrency & async", "domain", r"\bthread|\basync\b|\bawait\b|\bconcurren|\brace condition\b|\bdeadlock\b|\bparallel\b|\bmultiprocess|\bpromise\b"),
    _s("cli", "Command-line tools", "domain", r"\bcli\b|\bcommand[- ]line\b|\bargparse\b|\bclick\b|\bflag\b|\bterminal\b|\bstdout\b|\bstderr\b", r"(^|/)(cli|cmd|bin|commands?)/"),
    _s("parsing", "Parsers & compilers", "domain", r"\bpars(e|er|ing)\b|\bast\b|\blexer\b|\btokeni[sz]|\bgrammar\b|\bcompil", r"(^|/)(parser|lexer|ast|compiler)"),
    _s("data_processing", "Data processing", "domain", r"\bcsv\b|\bjson\b|\bparquet\b|\bserializ|\bschema\b|\betl\b|\bdatetime\b|\btimezone\b"),
    _s("machine_learning", "Machine learning", "domain", r"\bmodel\b.*\b(train|fit|predict)|\bclassifier\b|\bregression\b|\bneural\b|\bgradient\b|\bembedding\b", "", [], ["python"]),
    _s("visualization", "Data visualisation", "domain", r"\bplot\b|\bchart\b|\bgraph(ics)?\b|\bvisuali[sz]|\brender(er)?\b|\bcolormap\b"),
    _s("typing", "Type systems & typing", "domain", r"\btype hints?\b|\bmypy\b|\btyping\b|\bgenerics?\b|\btype (error|check)|\btypeddict\b|\binterface\b", r"\.pyi$|\.d\.ts$"),
    _s("debugging", "Debugging", "practice", r"\btraceback\b|\bstack ?trace\b|\bexception\b|\berror\b|\bcrash\b|\bregression\b|\bbug\b|\bpanic\b"),
    _s("devops_cloud", "Cloud & DevOps", "domain", r"\baws\b|\bgcp\b|\bazure\b|\bs3\b|\blambda\b|\bserverless\b|\bdeploy"),
]
SKILLS: dict[str, Skill] = {skill.id: skill for skill in TAXONOMY}
_LANGUAGE_SKILL = {"Python": "python", "JavaScript": "javascript", "TypeScript": "typescript", "Go": "go", "Rust": "rust", "Java": "java", "Kotlin": "kotlin", "Ruby": "ruby", "PHP": "php", "C": "c", "C++": "cpp", "C#": "csharp", "Swift": "swift", "Vue": "vue", "Svelte": "svelte", "Shell": "shell", "HTML": "html_css", "CSS": "html_css", "SCSS": "html_css", "Jupyter Notebook": "python"}
_TEXT = {skill.id: re.compile(skill.text, re.I) for skill in TAXONOMY if skill.text}
_PATH = {skill.id: re.compile(skill.path, re.I) for skill in TAXONOMY if skill.path}


def skill_name(skill_id: str) -> str:
    return SKILLS[skill_id].name if skill_id in SKILLS else skill_id


def _merge(target: dict[str, dict[str, Any]], skill_id: str, weight: float, evidence: str) -> None:
    entry = target.setdefault(skill_id, {"weight": 0.0, "evidence": []})
    # Noisy-OR accumulation keeps weights in [0, 1] while rewarding agreeing evidence.
    entry["weight"] = 1 - (1 - entry["weight"]) * (1 - min(max(weight, 0.0), 1.0))
    if evidence not in entry["evidence"] and len(entry["evidence"]) < 4:
        entry["evidence"].append(evidence)


def skills_from_text(text: str, weight: float = 0.6) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for skill_id, pattern in _TEXT.items():
        hits = pattern.findall(text or "")
        if hits:
            first = hits[0] if isinstance(hits[0], str) else next((part for part in hits[0] if part), "")
            _merge(found, skill_id, weight * min(1.0, 0.6 + 0.2 * len(hits)), f"mentions “{first.strip()[:30]}”")
    return found


def skills_from_paths(paths: Iterable[str], weight: float = 0.8) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    paths = list(paths)
    for path in paths:
        language = EXTENSION_LANGUAGE.get(PurePosixPath(path).suffix.lower())
        if language and language in _LANGUAGE_SKILL:
            _merge(found, _LANGUAGE_SKILL[language], weight, f"file {path}")
        for skill_id, pattern in _PATH.items():
            if pattern.search(path):
                _merge(found, skill_id, weight * 0.8, f"file {path}")
        if is_test_path(path):
            _merge(found, "testing", weight * 0.8, f"test {path}")
    return found


def skills_from_manifests(manifests: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    """``manifests`` maps manifest path -> content (package.json, requirements.txt, ...)."""
    packages: set[str] = set()
    for path, content in manifests.items():
        name = PurePosixPath(path).name.lower()
        if name == "package.json":
            try:
                data = json.loads(content)
                for key in ("dependencies", "devDependencies", "peerDependencies"):
                    packages.update(str(dep).lower() for dep in (data.get(key) or {}))
            except (ValueError, AttributeError):
                pass
        else:
            packages.update(match.lower() for match in re.findall(r"^\s*[\"']?([A-Za-z0-9_.@/-]+)", content or "", re.M))
    found: dict[str, dict[str, Any]] = {}
    for skill in TAXONOMY:
        for package in skill.packages:
            if package.lower() in packages:
                _merge(found, skill.id, 0.9, f"depends on {package}")
    return found


def combine(*vectors: Mapping[str, Mapping[str, Any]], scale: Iterable[float] | None = None) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for vector, factor in zip(vectors, scale or [1.0] * len(vectors)):
        for skill_id, entry in vector.items():
            for index, evidence in enumerate(entry.get("evidence") or ["inferred"]):
                _merge(merged, skill_id, entry["weight"] * factor if index == 0 else 0.0, evidence)
    return merged


def extract_issue_skills(title: str, body: str, labels: Iterable[str] = (), predicted_files: Iterable[str] = (), repo_skills: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Skills an issue requires: its text, the files it likely touches, and the repository's core stack."""
    text = f"{title}\n{title}\n{body}\n{' '.join(labels)}"  # title counted twice: it is the densest signal
    vectors = [skills_from_text(text), skills_from_paths(list(predicted_files)[:5], weight=0.7)]
    scales = [1.0, 1.0]
    if repo_skills:
        primary = {skill_id: entry for skill_id, entry in repo_skills.items() if SKILLS.get(skill_id, Skill("", "", "")).category in {"language", "framework"} and entry["weight"] >= 0.5}
        vectors.append(primary)
        scales.append(0.5)
    return combine(*vectors, scale=scales)


def extract_repository_skills(files: Iterable[str], manifests: Mapping[str, str] | None = None, languages: Mapping[str, int] | None = None, topics: Iterable[str] = ()) -> dict[str, dict[str, Any]]:
    files = list(files)
    found: dict[str, dict[str, Any]] = {}
    counts = Counter(EXTENSION_LANGUAGE.get(PurePosixPath(path).suffix.lower()) for path in files)
    total = sum(count for language, count in counts.items() if language) or 1
    for language, count in counts.items():
        if language in _LANGUAGE_SKILL and count / total >= 0.05:
            _merge(found, _LANGUAGE_SKILL[language], min(1.0, 0.4 + count / total), f"{count} {language} files")
    for language, size in (languages or {}).items():
        share = size / max(sum((languages or {}).values()), 1)
        if language in _LANGUAGE_SKILL and share >= 0.05:
            _merge(found, _LANGUAGE_SKILL[language], min(1.0, 0.4 + share), f"{share:.0%} of code is {language}")
    path_hits = Counter(skill_id for path in files for skill_id, pattern in _PATH.items() if pattern.search(path))
    for skill_id, count in path_hits.items():
        if count >= 3:
            _merge(found, skill_id, min(0.8, 0.3 + 0.1 * math.log1p(count)), f"{count} matching files")
    found = combine(found, skills_from_manifests(manifests or {}), skills_from_text(" ".join(topics), weight=0.7))
    return found


def contributor_skills(contributions: Iterable[Mapping[str, Any]], half_life_days: float | None = None) -> dict[str, dict[str, Any]]:
    """Proficiency from past contributions: each item has ``files`` and optional ``title``/``weight``.

    Proficiency saturates with repeated evidence: 1 - exp(-count / 3).
    """
    counts: defaultdict[str, float] = defaultdict(float)
    evidence: defaultdict[str, list[str]] = defaultdict(list)
    for contribution in contributions:
        weight = float(contribution.get("weight", 1.0))
        hits = combine(skills_from_paths(contribution.get("files") or [], weight=1.0), skills_from_text(contribution.get("title") or "", weight=0.5))
        for skill_id, entry in hits.items():
            counts[skill_id] += weight * entry["weight"]
            if len(evidence[skill_id]) < 3 and contribution.get("title"):
                evidence[skill_id].append(str(contribution["title"])[:80])
    return {skill_id: {"weight": float(1 - math.exp(-count / 3.0)), "evidence": evidence[skill_id] or ["past contributions"]} for skill_id, count in counts.items()}


def match_skills(contributor: Mapping[str, Mapping[str, Any]] | Mapping[str, float], required: Mapping[str, Mapping[str, Any]], gap_threshold: float = 0.35) -> dict[str, Any]:
    """Weighted coverage of required skills by contributor proficiency."""
    def weight(vector: Mapping[str, Any], skill_id: str) -> float:
        value = vector.get(skill_id, 0.0)
        return float(value.get("weight", 0.0) if isinstance(value, Mapping) else value)

    # Prerequisite credit: knowing TypeScript implies partial JavaScript, etc.
    def proficiency(skill_id: str) -> float:
        own = weight(contributor, skill_id)
        implied = max((0.6 * weight(contributor, other.id) for other in TAXONOMY if skill_id in other.prerequisites), default=0.0)
        return max(own, implied)

    total = sum(weight(required, skill_id) for skill_id in required) or 1.0
    covered = sum(weight(required, skill_id) * min(1.0, proficiency(skill_id)) for skill_id in required)
    matched = sorted(((skill_id, proficiency(skill_id)) for skill_id in required if proficiency(skill_id) >= gap_threshold), key=lambda item: -weight(required, item[0]))
    gaps = sorted((skill_id for skill_id in required if weight(required, skill_id) >= 0.4 and proficiency(skill_id) < gap_threshold), key=lambda skill_id: -weight(required, skill_id))
    return {
        "score": float(covered / total),
        "matched": [{"id": skill_id, "name": skill_name(skill_id), "proficiency": round(level, 3)} for skill_id, level in matched],
        "gaps": [{"id": skill_id, "name": skill_name(skill_id), "required": round(weight(required, skill_id), 3), "prerequisites": [skill_name(p) for p in SKILLS.get(skill_id, Skill("", "", "")).prerequisites]} for skill_id in gaps],
    }


def as_public(vector: Mapping[str, Mapping[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    ranked = sorted(vector.items(), key=lambda item: -item[1]["weight"])[:limit]
    return [{"id": skill_id, "name": skill_name(skill_id), "category": SKILLS[skill_id].category if skill_id in SKILLS else "other", "weight": round(entry["weight"], 3), "evidence": entry.get("evidence", [])} for skill_id, entry in ranked]


__all__ = ["SKILLS", "TAXONOMY", "as_public", "combine", "contributor_skills", "extract_issue_skills", "extract_repository_skills", "match_skills", "skill_name", "skills_from_manifests", "skills_from_paths", "skills_from_text"]
