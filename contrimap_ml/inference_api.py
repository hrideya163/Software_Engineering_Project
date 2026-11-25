"""Backward-compatible entry point: ``uvicorn contrimap_ml.inference_api:app``.

The full backend now lives in :mod:`contrimap_ml.api`; the legacy routes
(``/api/predict``, ``/api/analyze``, ``/api/repositories/issues``) are served there.
"""

from .api import app

__all__ = ["app"]
