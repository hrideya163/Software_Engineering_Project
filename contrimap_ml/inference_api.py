"""HTTP inference service for the saved ContriMap model artifacts."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .inference import GitHubInferenceError, analyzeIssue, fetchRepositoryIssues, load_models


class PredictionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    body: str = Field(default="", max_length=100_000)
    labels: list[str] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=10, ge=1, le=50)


class FilePrediction(BaseModel):
    path: str
    similarity: float


class PredictionResponse(BaseModel):
    model_version: str
    difficulty: str
    difficulty_probability: float
    effort_hours: float
    files: list[FilePrediction]


ARTIFACT_DIR = Path(os.getenv("CONTRIMAP_ARTIFACT_DIR", Path(__file__).resolve().parent.parent / "artifacts"))
MODEL_VERSION = os.getenv("CONTRIMAP_MODEL_VERSION", ARTIFACT_DIR.name)
models = load_models()
app = FastAPI(title="ContriMap ML Inference API", version=MODEL_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CONTRIMAP_ALLOWED_ORIGINS", "").split(",") if origin.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model_version": MODEL_VERSION}


@app.post("/api/predict", response_model=PredictionResponse)
def predict(request: PredictionRequest) -> PredictionResponse:
    try:
        result = models.predict(request.title, request.body, request.labels, request.top_k)
    except (ValueError, RuntimeError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return PredictionResponse(model_version=MODEL_VERSION, **result)


class RepositoryRequest(BaseModel):
    repository_url: str = Field(alias="repositoryUrl")


class IssueRequest(RepositoryRequest):
    issue: dict[str, object]


@app.post("/api/repositories/issues")
def repository_issues(request: RepositoryRequest) -> list[dict[str, object]]:
    try:
        return fetchRepositoryIssues(request.repository_url)
    except (GitHubInferenceError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/analyze")
def analyze(request: IssueRequest) -> dict[str, object]:
    try:
        return analyzeIssue(request.repository_url, request.issue)
    except (GitHubInferenceError, ValueError, RuntimeError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
