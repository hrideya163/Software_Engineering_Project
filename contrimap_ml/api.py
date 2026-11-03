"""ContriMap FastAPI backend.

    uvicorn contrimap_ml.api:app --port 8001

All model inference, repository analysis and recommendations are served here;
the Express server (``server/``) keeps only GitHub/Google sign-in.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "server" / ".env")

from . import service  # noqa: E402  (environment must be loaded first)
from .skills import as_public, skills_from_text  # noqa: E402

NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")

app = FastAPI(title="ContriMap API", version="2.0.0")
origins = [origin.strip() for origin in os.getenv("CONTRIMAP_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


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


class IssueInput(BaseModel):
    number: int | None = None
    title: str = Field(min_length=1, max_length=1000)
    body: str = Field(default="", max_length=100_000)
    labels: list[Any] = Field(default_factory=list, max_length=50)


class AnalyzeRequest(BaseModel):
    issue: IssueInput | None = None
    profile: Profile | None = None
    explain: bool = True


class RecommendationRequest(BaseModel):
    profile: Profile
    repositories: list[str] = Field(min_length=1, max_length=6)
    mode: str = Field(default="balanced", pattern="^(balanced|learning|quick_win)$")
    per_repository: int = Field(default=15, ge=1, le=40)
    limit: int = Field(default=20, ge=1, le=60)


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


@app.get("/api/repos/{owner}/{repo}")
def repository(owner: str, repo: str) -> dict[str, Any]:
    return service.repository_overview(*_repo(owner, repo))


@app.get("/api/repos/{owner}/{repo}/issues")
def issues(owner: str, repo: str, limit: int = 30) -> dict[str, Any]:
    return service.ranked_issues(*_repo(owner, repo), None, limit=max(1, min(limit, 60)))


@app.post("/api/repos/{owner}/{repo}/issues/ranked")
def personalised_issues(owner: str, repo: str, request: ProfileRequest) -> dict[str, Any]:
    return service.ranked_issues(*_repo(owner, repo), _profile(request.profile), request.mode, request.limit)


@app.post("/api/repos/{owner}/{repo}/learning")
def learning(owner: str, repo: str, request: ProfileRequest) -> dict[str, Any]:
    if request.profile is None:
        raise HTTPException(422, "A profile is required for learning opportunities.")
    return service.learning_opportunities(*_repo(owner, repo), _profile(request.profile))


@app.get("/api/repos/{owner}/{repo}/issues/{number}/analysis")
def issue_analysis(owner: str, repo: str, number: int) -> dict[str, Any]:
    owner, repo = _repo(owner, repo)
    return service.analyze_issue(owner, repo, service.get_issue(owner, repo, number))


@app.post("/api/repos/{owner}/{repo}/issues/{number}/analysis")
def issue_analysis_personal(owner: str, repo: str, number: int, request: AnalyzeRequest) -> dict[str, Any]:
    owner, repo = _repo(owner, repo)
    issue = request.issue.model_dump() if request.issue else service.get_issue(owner, repo, number)
    return service.analyze_issue(owner, repo, issue, _profile(request.profile), request.explain)


@app.post("/api/repos/{owner}/{repo}/analyze")
def analyze_text(owner: str, repo: str, request: AnalyzeRequest) -> dict[str, Any]:
    """Analyse an arbitrary (e.g. draft) issue against a repository."""
    if request.issue is None:
        raise HTTPException(422, "issue is required.")
    return service.analyze_issue(*_repo(owner, repo), request.issue.model_dump(), _profile(request.profile), request.explain)


@app.get("/api/repos/{owner}/{repo}/architecture")
def architecture(owner: str, repo: str) -> dict[str, Any]:
    return service.architecture(*_repo(owner, repo))


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
    merged: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for full_name in request.repositories:
        owner, _, repo = full_name.partition("/")
        try:
            result = service.ranked_issues(*_repo(owner, repo), _profile(request.profile), request.mode, request.per_repository)
        except (service.GitHubError, HTTPException) as error:
            errors[full_name] = str(getattr(error, "detail", error))
            continue
        merged.extend({**item, "repository": result["repository"]} for item in result["issues"])
    merged.sort(key=lambda item: -item["score"])
    for rank, item in enumerate(merged, 1):
        item["rank"] = rank
    return {"issues": merged[: request.limit], "errors": errors, "mode": request.mode}


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
