"""ContriMap FastAPI backend.

    uvicorn contrimap_ml.api:app --port 8001

All model inference, repository analysis, recommendations and GitHub/Google sign-in
(``auth.py``) are served here.
"""

from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from . import auth, service  # noqa: E402  (environment must be loaded first)
from .skills import as_public, skills_from_text  # noqa: E402

NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the trained models and the sentence embedder in the background at startup, so the first ranking
    request does not pay the ~15 s embedder load. Requests that arrive earlier still work (they wait)."""
    if os.getenv("CONTRIMAP_WARMUP", "1") != "0":
        import threading

        def run() -> None:
            try:
                from .textfeat import embed

                service.models()
                embed(["warm up"], cache=False)
            except Exception:  # noqa: BLE001 - warm-up is best effort
                pass

        threading.Thread(target=run, name="contrimap-warmup", daemon=True).start()
    yield


app = FastAPI(title="ContriMap API", version="2.0.0", lifespan=lifespan)
origins = [origin.strip() for origin in os.getenv("CONTRIMAP_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
app.include_router(auth.router)


@app.middleware("http")
async def server_timing(request: Request, call_next):
    """Report server time per request (Server-Timing), so browser traces separate server work from waiting."""
    import time as _time

    start = _time.perf_counter()
    response = await call_next(request)
    response.headers["Server-Timing"] = f"app;dur={(_time.perf_counter() - start) * 1000:.1f}"
    response.headers["Timing-Allow-Origin"] = "*"
    return response


@app.exception_handler(service.GitHubError)
def github_error(_: Request, error: service.GitHubError) -> JSONResponse:
    return JSONResponse(status_code=error.status if error.status in (404, 429) else 502, content={"detail": str(error)})


def _repo(owner: str, repo: str) -> tuple[str, str]:
    if not NAME.match(owner) or not NAME.match(repo):
        raise HTTPException(422, "Invalid owner or repository name.")
    return owner, repo.removesuffix(".git")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class Profile(BaseModel):
    level: str = Field(default="intermediate", pattern="^(beginner|intermediate|advanced)$")
    tech_stack: list[str] = Field(default_factory=list, max_length=30)
    interests: list[str] = Field(default_factory=list, max_length=20)
    learning_goals: list[str] = Field(default_factory=list, max_length=20)
    time_budget_hours: float | None = Field(default=None, ge=0, le=500)
    login: str | None = Field(default=None, max_length=100)
    history: dict[str, int] | None = None  # {"prior_prs": n, "prior_merged": m} in the target repository


class ProfileRequest(BaseModel):
    profile: Profile | None = None
    mode: str = Field(default="balanced", pattern="^(balanced|learning|quick_win)$")
    limit: int = Field(default=30, ge=1, le=60)
    user: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,64}$")  # feedback id (GitHub login or a browser id)


class FeedbackRequest(BaseModel):
    user: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
    number: int = Field(ge=1)
    action: str = Field(pattern="^(opened|saved|unsaved|dismissed|restored|completed)$")
    title: str = Field(default="", max_length=1000)
    text: str = Field(default="", max_length=20_000)


class IssueInput(BaseModel):
    number: int | None = None
    title: str = Field(min_length=1, max_length=1000)
    body: str = Field(default="", max_length=100_000)
    labels: list[Any] = Field(default_factory=list, max_length=50)


class AnalyzeRequest(BaseModel):
    issue: IssueInput | None = None
    profile: Profile | None = None
    explain: bool = True


class ExplanationRequest(BaseModel):
    profile: Profile | None = None
    generate: bool = False  # True only when the user asks for a Claude-written explanation


class ProfileSaveRequest(BaseModel):
    profile: Profile


class RecommendationRequest(BaseModel):
    profile: Profile
    repositories: list[str] = Field(min_length=1, max_length=6)
    mode: str = Field(default="balanced", pattern="^(balanced|learning|quick_win)$")
    per_repository: int = Field(default=15, ge=1, le=40)
    limit: int = Field(default=20, ge=1, le=60)
    user: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,64}$")


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)


def _profile(profile: Profile | None) -> dict[str, Any] | None:
    return profile.model_dump() if profile else None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", **service.health()}


@app.get("/api/model-card")
def model_card() -> dict[str, Any]:
    return service.models().report


@app.get("/api/trending")
def trending(language: str | None = None, limit: int = 12) -> dict[str, Any]:
    if language and not re.fullmatch(r"[A-Za-z0-9+#. -]{1,30}", language):
        raise HTTPException(422, "Invalid language.")
    return service.trending(language, max(1, min(limit, 30)))


@app.post("/api/repos/{owner}/{repo}/prepare")
def prepare(owner: str, repo: str) -> dict[str, Any]:
    """Start snapshotting the repository and building its graph in the background; poll ``/status``."""
    return service.prepare_repository(*_repo(owner, repo))


@app.get("/api/repos/{owner}/{repo}/status")
def preparation_status(owner: str, repo: str) -> dict[str, Any]:
    return service.preparation_status(*_repo(owner, repo))


@app.get("/api/repos/{owner}/{repo}")
def repository(owner: str, repo: str) -> dict[str, Any]:
    return service.repository_overview(*_repo(owner, repo))


@app.get("/api/repos/{owner}/{repo}/issues")
def issues(owner: str, repo: str, limit: int = 30, user: str | None = None) -> dict[str, Any]:
    if user is not None and not NAME.match(user):
        raise HTTPException(422, "Invalid user id.")
    return service.ranked_issues(*_repo(owner, repo), None, limit=max(1, min(limit, 60)), user=user)


@app.post("/api/repos/{owner}/{repo}/issues/ranked")
def personalised_issues(owner: str, repo: str, request: ProfileRequest) -> dict[str, Any]:
    return service.ranked_issues(*_repo(owner, repo), _profile(request.profile), request.mode, request.limit, user=request.user)


@app.post("/api/repos/{owner}/{repo}/learning")
def learning(owner: str, repo: str, request: ProfileRequest) -> dict[str, Any]:
    if request.profile is None:
        raise HTTPException(422, "A profile is required for learning opportunities.")
    return service.learning_opportunities(*_repo(owner, repo), _profile(request.profile))


def _issue_and_context(owner: str, repo: str, number: int) -> dict[str, Any]:
    """Fetch the issue from GitHub while the repository context (snapshot, graph) loads: the two are independent."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        context = pool.submit(service.repository_context, owner, repo)
        issue = service.get_issue(owner, repo, number)
        context.result()
    return issue


@app.get("/api/repos/{owner}/{repo}/issues/{number}")
def issue_details(owner: str, repo: str, number: int) -> dict[str, Any]:
    """Just the issue (title, labels, author...), so the page can show it before the analysis is ready."""
    owner, repo = _repo(owner, repo)
    return {"repository": f"{owner}/{repo}", "issue": service.get_issue(owner, repo, number)}


@app.get("/api/repos/{owner}/{repo}/issues/{number}/analysis")
def issue_analysis(owner: str, repo: str, number: int) -> dict[str, Any]:
    owner, repo = _repo(owner, repo)
    return service.analyze_issue(owner, repo, _issue_and_context(owner, repo, number))


@app.post("/api/repos/{owner}/{repo}/issues/{number}/analysis")
def issue_analysis_personal(owner: str, repo: str, number: int, request: AnalyzeRequest) -> dict[str, Any]:
    owner, repo = _repo(owner, repo)
    issue = request.issue.model_dump() if request.issue else _issue_and_context(owner, repo, number)
    return service.analyze_issue(owner, repo, issue, _profile(request.profile), request.explain)


@app.post("/api/repos/{owner}/{repo}/analyze")
def analyze_text(owner: str, repo: str, request: AnalyzeRequest) -> dict[str, Any]:
    """Analyse an arbitrary (e.g. draft) issue against a repository."""
    if request.issue is None:
        raise HTTPException(422, "issue is required.")
    return service.analyze_issue(*_repo(owner, repo), request.issue.model_dump(), _profile(request.profile), request.explain)


@app.get("/api/repos/{owner}/{repo}/issues/{number}/explanation")
def issue_explanation(owner: str, repo: str, number: int) -> dict[str, Any]:
    """Stored Claude explanation for this analysis if one exists, else the template. Never calls the LLM."""
    owner, repo = _repo(owner, repo)
    return service.explanation(owner, repo, service.get_issue(owner, repo, number), None, generate=False)


@app.post("/api/repos/{owner}/{repo}/issues/{number}/explanation")
def issue_explanation_personal(owner: str, repo: str, number: int, request: ExplanationRequest) -> dict[str, Any]:
    """With ``generate``, writes (and stores) a Claude explanation when an API key is configured."""
    owner, repo = _repo(owner, repo)
    return service.explanation(owner, repo, service.get_issue(owner, repo, number), _profile(request.profile), generate=request.generate)


@app.get("/api/profiles/{user}")
def get_profile(user: str) -> dict[str, Any]:
    if not NAME.match(user):
        raise HTTPException(422, "Invalid user id.")
    return {"user": user, "profile": service.load_profile(user)}


@app.post("/api/profiles/{user}")
def save_profile(user: str, request: ProfileSaveRequest) -> dict[str, Any]:
    if not NAME.match(user):
        raise HTTPException(422, "Invalid user id.")
    return {"user": user, "profile": service.save_profile(user, request.profile.model_dump()), "stored": service.store_name()}


@app.get("/api/repos/{owner}/{repo}/architecture")
def architecture(owner: str, repo: str) -> dict[str, Any]:
    return service.architecture(*_repo(owner, repo))


@app.get("/api/repos/{owner}/{repo}/activity")
def activity(owner: str, repo: str) -> dict[str, Any]:
    return service.repository_activity(*_repo(owner, repo))


@app.get("/api/repos/{owner}/{repo}/issues/{number}/similar")
def similar(owner: str, repo: str, number: int) -> dict[str, Any]:
    owner, repo = _repo(owner, repo)
    issue = service.get_issue(owner, repo, number)
    # Same cache entry as the analysis page, so this is free once the issue has been analysed.
    predicted = [f["path"] for f in service.analyze_issue(owner, repo, issue, with_explanation=False)["files"][:10]]
    return service.similar_history(owner, repo, issue, predicted=predicted)


@app.get("/api/repos/{owner}/{repo}/module")
def module(owner: str, repo: str, directory: str, tests: bool = False, issue: int | None = None) -> dict[str, Any]:
    owner, repo = _repo(owner, repo)
    if len(directory) > 500 or ".." in directory:
        raise HTTPException(422, "Invalid directory.")
    highlight = []
    if issue is not None:
        highlight = service.analyze_issue(owner, repo, service.get_issue(owner, repo, issue), with_explanation=False)["architecture_highlight"]
    return service.module_graph(owner, repo, directory, include_tests=tests, highlight=highlight)


@app.get("/api/repos/{owner}/{repo}/file")
def file(owner: str, repo: str, path: str) -> dict[str, Any]:
    if len(path) > 500 or ".." in path:
        raise HTTPException(422, "Invalid path.")
    return service.file_inspector(*_repo(owner, repo), path)


@app.post("/api/feedback")
def record_feedback(request: FeedbackRequest) -> dict[str, Any]:
    from . import feedback

    owner, _, repo = request.repository.partition("/")
    _repo(owner, repo)
    event = feedback.record(request.user, request.repository, request.number, request.action, request.title, request.text)
    return {"recorded": event, "state": feedback.state(request.user, request.repository).get(f"{request.repository.lower()}#{request.number}")}


@app.get("/api/feedback/{user}")
def feedback_summary(user: str) -> dict[str, Any]:
    from . import feedback

    if not NAME.match(user):
        raise HTTPException(422, "Invalid user id.")
    return feedback.summary(user)


@app.get("/api/repos/{owner}/{repo}/tree")
def tree(owner: str, repo: str) -> dict[str, Any]:
    from .codegraph import file_tree

    context = service.repository_context(*_repo(owner, repo))
    return file_tree(context["snapshot"]["files"])


@app.get("/api/contributors/{login}")
def contributor(login: str) -> dict[str, Any]:
    if not NAME.match(login):
        raise HTTPException(422, "Invalid login.")
    return service.contributor_profile(login)


@app.post("/api/recommendations")
def recommendations(request: RecommendationRequest) -> dict[str, Any]:
    """Personalised issues across several repositories, merged by score."""
    from concurrent.futures import ThreadPoolExecutor

    merged: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    weights: dict[str, float] = {}
    hidden = 0
    profile = _profile(request.profile)

    def rank_repository(full_name: str) -> dict[str, Any]:
        owner, _, repo = full_name.partition("/")
        return service.ranked_issues(*_repo(owner, repo), profile, request.mode, request.per_repository, user=request.user)

    # Repositories are independent (git snapshots, issue lists), so they are ranked concurrently.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {full_name: pool.submit(rank_repository, full_name) for full_name in dict.fromkeys(request.repositories)}
    for full_name, future in futures.items():
        try:
            result = future.result()
        except (service.GitHubError, HTTPException) as error:
            errors[full_name] = str(getattr(error, "detail", error))
            continue
        weights = weights or result.get("weights") or {}
        hidden += len(result.get("hidden") or [])
        merged.extend({**item, "repository": result["repository"]} for item in result["issues"])
    merged.sort(key=lambda item: -item["score"])
    for rank, item in enumerate(merged, 1):
        item["rank"] = rank
    # Same profile and mode for every repository, so the weights are shared; the frontend uses them to explain scores.
    return {"issues": merged[: request.limit], "errors": errors, "mode": request.mode, "weights": weights, "hidden": hidden, "searched": [name for name in dict.fromkeys(request.repositories) if name not in errors]}


@app.post("/api/skills/extract")
def extract_skills(request: TextRequest) -> dict[str, Any]:
    return {"skills": as_public(skills_from_text(request.text))}


# ---------------------------------------------------------------------------
# Legacy routes (kept for existing clients of contrimap_ml.inference_api)
# ---------------------------------------------------------------------------
class LegacyPredictRequest(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    body: str = Field(default="", max_length=100_000)
    labels: list[str] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=10, ge=1, le=50)


@app.post("/api/predict")
def legacy_predict(request: LegacyPredictRequest) -> dict[str, Any]:
    """Text-only difficulty/effort (no repository => no file localization)."""
    result = service.models().difficulty.predict_one(request.title, request.body, request.labels)
    return {"model_version": "v2", **result, "files": []}


class LegacyRepositoryRequest(BaseModel):
    repositoryUrl: str


class LegacyAnalyzeRequest(LegacyRepositoryRequest):
    issue: dict[str, Any]


def _parse_url(url: str) -> tuple[str, str]:
    match = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", url.strip())
    if not match:
        raise HTTPException(422, "repositoryUrl must be https://github.com/{owner}/{repo}.")
    return match.group(1), match.group(2)


@app.post("/api/repositories/issues")
def legacy_issues(request: LegacyRepositoryRequest) -> list[dict[str, Any]]:
    return service.list_issues(*_parse_url(request.repositoryUrl))


@app.post("/api/analyze")
def legacy_analyze(request: LegacyAnalyzeRequest) -> dict[str, Any]:
    owner, repo = _parse_url(request.repositoryUrl)
    issue = dict(request.issue)
    if not str(issue.get("title") or "").strip():
        raise HTTPException(422, "issue.title is required.")
    result = service.analyze_issue(owner, repo, issue, with_explanation=False)
    return {**result, "affected_files": [{"path": f["path"], "similarity": f["relative_confidence"]} for f in result["files"]]}


# ---------------------------------------------------------------------------
# Optional: serve the built frontend (single-container deployment)
# ---------------------------------------------------------------------------
DIST = Path(os.getenv("CONTRIMAP_FRONTEND_DIST", ROOT / "dist"))
if os.getenv("CONTRIMAP_SERVE_FRONTEND") == "1" and DIST.exists():
    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        candidate = (DIST / path).resolve()
        if path and candidate.is_file() and DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
