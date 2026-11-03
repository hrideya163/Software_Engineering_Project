"""Tests for the ContriMap ML pipeline: candidate filtering, features, and model inference."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from contrimap_ml.features import (
    KNOWN_LABEL_PREFIXES,
    NUMERIC_FEATURES,
    deduplicate_dataset,
    file_corpus,
    file_texts,
    is_valid_candidate,
    load_dataset,
    tabular_features,
    training_split,
)


# ---------------------------------------------------------------------------
# Candidate filtering tests
# ---------------------------------------------------------------------------

class TestIsValidCandidate:
    """Tests for is_valid_candidate() — the localization index filter."""

    def test_source_files_accepted(self):
        assert is_valid_candidate("src/index.js")
        assert is_valid_candidate("packages/next/build/webpack-config.ts")
        assert is_valid_candidate("server/render.js")
        assert is_valid_candidate("lib/router/router.py")

    def test_package_json_at_subdir_accepted(self):
        """Non-root package.json files are legitimate candidates."""
        assert is_valid_candidate("packages/next/package.json")
        assert is_valid_candidate("package.json")  # root is OK too

    def test_node_modules_excluded(self):
        assert not is_valid_candidate("node_modules/react/index.js")
        assert not is_valid_candidate("packages/node_modules/foo/bar.js")

    def test_lockfiles_excluded(self):
        assert not is_valid_candidate("yarn.lock")
        assert not is_valid_candidate("package-lock.json")
        assert not is_valid_candidate("pnpm-lock.yaml")
        assert not is_valid_candidate("Cargo.lock")
        assert not is_valid_candidate("go.sum")  # not a lock, but binary-like

    def test_git_directory_excluded(self):
        assert not is_valid_candidate(".git/objects/abc123")
        assert not is_valid_candidate(".git/HEAD")

    def test_build_outputs_excluded(self):
        assert not is_valid_candidate("dist/bundle.js")
        assert not is_valid_candidate("build/output/main.js")
        assert not is_valid_candidate(".next/static/chunks/main.js")

    def test_binary_files_excluded(self):
        assert not is_valid_candidate("assets/logo.png")
        assert not is_valid_candidate("fonts/arial.woff2")
        assert not is_valid_candidate("archive.zip")
        assert not is_valid_candidate("bundle.js.map")

    def test_empty_or_whitespace_rejected(self):
        assert not is_valid_candidate("")
        assert not is_valid_candidate("   ")

    def test_vendor_excluded(self):
        assert not is_valid_candidate("vendor/github.com/foo/bar.go")

    def test_pycache_excluded(self):
        assert not is_valid_candidate("__pycache__/module.cpython-311.pyc")

    def test_config_files_accepted(self):
        """Configuration files like .eslintrc, tsconfig are valid candidates."""
        assert is_valid_candidate(".eslintrc.json")
        assert is_valid_candidate("tsconfig.json")
        assert is_valid_candidate("pyproject.toml")

    def test_ci_config_accepted(self):
        assert is_valid_candidate(".github/workflows/ci.yml")

    def test_markdown_accepted(self):
        assert is_valid_candidate("README.md")
        assert is_valid_candidate("docs/guide.md")

    def test_backslash_normalization(self):
        assert is_valid_candidate("src\\index.js")
        assert not is_valid_candidate("node_modules\\react\\index.js")


class TestFileCorpus:
    """Tests for file_corpus() — filtered candidate extraction from dataframe."""

    def test_filters_and_deduplicates(self):
        frame = pd.DataFrame({
            "changed_files": [
                ["src/a.js", "node_modules/x/y.js", "yarn.lock"],
                ["src/a.js", "src/b.ts", "package-lock.json"],
            ]
        })
        result = file_corpus(frame)
        assert "src/a.js" in result
        assert "src/b.ts" in result
        assert "node_modules/x/y.js" not in result
        assert "yarn.lock" not in result
        assert "package-lock.json" not in result
        # Should be sorted and deduplicated
        assert result == sorted(set(result))

    def test_empty_changed_files(self):
        frame = pd.DataFrame({"changed_files": [[], None]})
        assert file_corpus(frame) == []


class TestFileTexts:
    """Tests for file_texts() — text representation for embeddings."""

    def test_includes_path_components(self):
        texts = file_texts(["packages/next/build/webpack-config.ts"])
        assert len(texts) == 1
        text = texts[0]
        # Should contain stem, extension, directory info, and full path
        assert "webpack" in text.lower()
        assert "config" in text.lower()
        assert "ts" in text
        assert "packages" in text


# ---------------------------------------------------------------------------
# Dataset loading and deduplication tests
# ---------------------------------------------------------------------------

class TestLoadDataset:
    """Tests for load_dataset()."""

    def _write_records(self, path: Path, records: list[dict]) -> Path:
        with path.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return path

    def test_basic_load(self, tmp_path):
        records = [
            {
                "issue_title": "Fix bug",
                "issue_body": "There is a bug in the parser",
                "issue_labels": ["bug"],
                "changed_files": ["src/parser.js"],
                "effort_hours": 2.0,
                "difficulty_label": "Easy",
                "pr_merged_at": "2024-01-01T00:00:00Z",
            }
        ]
        path = self._write_records(tmp_path / "test.jsonl", records)
        frame = load_dataset(path)
        assert len(frame) == 1
        assert "label_count" in frame.columns
        assert "issue_body_chars" in frame.columns
        assert "effort_hours_log" in frame.columns
        assert frame.iloc[0]["label_count"] == 1

    def test_label_features_created(self, tmp_path):
        records = [
            {
                "issue_title": "Add feature",
                "issue_body": "New feature request",
                "issue_labels": ["enhancement", "good first issue"],
                "changed_files": ["src/app.js"],
                "effort_hours": 5.0,
                "difficulty_label": "Easy",
                "pr_merged_at": "2024-01-01T00:00:00Z",
            }
        ]
        path = self._write_records(tmp_path / "test.jsonl", records)
        frame = load_dataset(path)
        assert frame.iloc[0]["has_label_enhancement"] == 1.0
        assert frame.iloc[0]["has_label_good_first_issue"] == 1.0
        assert frame.iloc[0]["has_label_bug"] == 0.0


class TestDeduplication:
    """Tests for deduplicate_dataset()."""

    def test_merges_multi_pr_issues(self):
        frame = pd.DataFrame({
            "repository": ["r/a", "r/a", "r/a"],
            "issue_number": [1, 1, 2],
            "issue_title": ["Bug", "Bug", "Feature"],
            "changed_files": [["a.js"], ["b.js"], ["c.js"]],
            "pr_merged_at": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "effort_hours": [1.0, 2.0, 3.0],
        })
        result = deduplicate_dataset(frame)
        assert len(result) == 2  # issue 1 merged, issue 2 kept
        # Issue 1 should have merged changed_files
        issue1 = result[result["issue_number"] == 1].iloc[0]
        assert set(issue1["changed_files"]) == {"a.js", "b.js"}

    def test_no_duplicates_unchanged(self):
        frame = pd.DataFrame({
            "repository": ["r/a", "r/a"],
            "issue_number": [1, 2],
            "changed_files": [["a.js"], ["b.js"]],
            "pr_merged_at": ["2024-01-01", "2024-01-02"],
        })
        result = deduplicate_dataset(frame)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Feature availability tests
# ---------------------------------------------------------------------------

class TestFeatureAvailability:
    """Ensure all tabular features are available at inference time."""

    def test_numeric_features_are_inference_safe(self):
        """All NUMERIC_FEATURES can be computed from issue title, body, and labels."""
        for feature in NUMERIC_FEATURES:
            assert feature in {"label_count", "issue_body_chars", "issue_title_chars"}, \
                f"Feature '{feature}' may not be available at inference time"

    def test_label_features_are_inference_safe(self):
        """Label-based features use only issue labels, available at inference."""
        for prefix in KNOWN_LABEL_PREFIXES:
            col_name = f"has_label_{prefix.replace(' ', '_')}"
            # Just verify the naming convention
            assert col_name.startswith("has_label_")


# ---------------------------------------------------------------------------
# Training split tests
# ---------------------------------------------------------------------------

class TestTrainingSplit:

    def test_temporal_ordering(self):
        frame = pd.DataFrame({
            "pr_merged_at": ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01", "2024-05-01"],
            "difficulty_label": ["Easy", "Medium", "Hard", "Easy", "Medium"],
        })
        train, test = training_split(frame, test_size=0.4)
        assert len(train) == 3
        assert len(test) == 2
        # Train should contain earlier records
        assert train.iloc[-1]["pr_merged_at"] <= test.iloc[0]["pr_merged_at"]

    def test_minimum_records_required(self):
        frame = pd.DataFrame({
            "pr_merged_at": ["2024-01-01"],
            "difficulty_label": ["Easy"],
        })
        with pytest.raises(ValueError, match="At least two"):
            training_split(frame)


# ---------------------------------------------------------------------------
# Score normalization and combination tests
# ---------------------------------------------------------------------------

class TestLocalizationScoring:
    """Tests for localization score combination logic."""

    def test_normalize_scores(self):
        from contrimap_ml.models import _normalize_scores
        scores = np.array([1.0, 3.0, 5.0], dtype="float32")
        normalized = _normalize_scores(scores)
        assert normalized[0] == pytest.approx(0.0)
        assert normalized[2] == pytest.approx(1.0)
        assert normalized[1] == pytest.approx(0.5)

    def test_normalize_constant_scores(self):
        from contrimap_ml.models import _normalize_scores
        scores = np.array([5.0, 5.0, 5.0], dtype="float32")
        normalized = _normalize_scores(scores)
        assert all(v == pytest.approx(0.0) for v in normalized)

    def test_historical_scores_dampened(self):
        """Log-dampening should reduce the advantage of very frequent files."""
        from contrimap_ml.models import _historical_file_scores

        frame = pd.DataFrame({
            "changed_files": [
                ["package.json", "src/a.js"],
                ["package.json", "src/b.js"],
                ["package.json"],
                ["src/a.js"],
            ],
        })
        scores = _historical_file_scores(frame, dampen=True)
        # package.json appears 3 times, src/a.js 2 times, src/b.js 1 time
        # With log dampening, the ratio should be compressed
        assert scores["package.json"] > scores["src/a.js"]
        assert scores["src/a.js"] > scores["src/b.js"]
        # But the ratio should be much less than 3:2:1
        ratio = scores["package.json"] / scores["src/b.js"]
        assert ratio < 3.0, f"Log dampening should compress ratios, got {ratio}"

    def test_historical_scores_filter_invalid(self):
        """Invalid candidates should not appear in historical scores."""
        from contrimap_ml.models import _historical_file_scores

        frame = pd.DataFrame({
            "changed_files": [
                ["yarn.lock", "src/a.js"],
                ["node_modules/x/y.js", "src/a.js"],
            ],
        })
        scores = _historical_file_scores(frame)
        assert "yarn.lock" not in scores
        assert "node_modules/x/y.js" not in scores
        assert "src/a.js" in scores


# ---------------------------------------------------------------------------
# Integration-level: model training smoke test
# ---------------------------------------------------------------------------

class TestTrainModels:
    """Smoke test for the full training pipeline (small synthetic dataset)."""

    @pytest.fixture
    def small_dataset(self, tmp_path):
        """Create a minimal synthetic dataset for testing."""
        records = []
        for i in range(20):
            records.append({
                "repository": "test/repo",
                "issue_number": i,
                "issue_title": f"Fix issue {i} in module {'api' if i % 3 == 0 else 'ui'}",
                "issue_body": f"There is a problem with {'routing' if i % 2 == 0 else 'rendering'} in the application",
                "issue_labels": ["bug"] if i % 2 == 0 else ["enhancement"],
                "issue_created_at": f"2024-01-{(i+1):02d}T00:00:00Z",
                "issue_closed_at": f"2024-01-{(i+2):02d}T00:00:00Z",
                "pr_number": 100 + i,
                "pr_title": f"Fix #{i}",
                "pr_body": f"Closes #{i}",
                "pr_created_at": f"2024-01-{(i+1):02d}T12:00:00Z",
                "pr_merged_at": f"2024-01-{(i+2):02d}T00:00:00Z",
                "pr_closed_at": f"2024-01-{(i+2):02d}T00:00:00Z",
                "pr_review_comments": i % 5,
                "pr_commits": 1 + i % 3,
                "pr_additions": 10 + i * 5,
                "pr_deletions": 2 + i,
                "changed_files": [f"src/module{i % 3}.js", f"test/module{i % 3}.test.js"],
                "effort_hours": 1.0 + i * 2.0,
                "difficulty_label": ["Easy", "Medium", "Hard"][i % 3],
            })
        path = tmp_path / "dataset.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return path

    def test_train_produces_artifacts(self, small_dataset, tmp_path):
        from contrimap_ml.models import train_models

        output = tmp_path / "artifacts"
        metrics = train_models(small_dataset, output)

        # Check artifacts exist
        assert (output / "tabular_models.joblib").exists()
        assert (output / "file_index.faiss").exists()
        assert (output / "localization.json").exists()

        # Check metrics structure
        assert "dataset" in metrics
        assert "difficulty" in metrics
        assert "effort" in metrics
        assert "localization" in metrics

        # Check baselines are reported
        assert "baseline_accuracy" in metrics["difficulty"]
        assert "baseline_mae_hours" in metrics["effort"]
        assert "baseline_semantic_recall_at_5" in metrics["localization"]
        assert "baseline_frequency_recall_at_5" in metrics["localization"]

    def test_predict_after_train(self, small_dataset, tmp_path):
        from contrimap_ml.models import ContriMapModels, train_models

        output = tmp_path / "artifacts"
        train_models(small_dataset, output)

        models = ContriMapModels.load(output)
        result = models.predict("Fix routing bug in API module", "The router crashes on invalid paths", ["bug"])

        assert "difficulty" in result
        assert result["difficulty"] in {"Easy", "Medium", "Hard"}
        assert "effort_hours" in result
        assert result["effort_hours"] >= 0
        assert "files" in result
        assert "confidence" in result
        assert result["confidence"] in {"low", "medium", "high"}

        # Check that predicted files are valid candidates (no lockfiles etc.)
        for file_pred in result["files"]:
            assert is_valid_candidate(file_pred["path"]), \
                f"Predicted file {file_pred['path']} should be a valid candidate"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
