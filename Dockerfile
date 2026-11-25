# Single image: built React frontend + FastAPI backend + trained artifacts.
#   docker build -t contrimap .
#   docker run -p 8001:8001 --env-file .env contrimap      -> http://localhost:8001
# Trained models come from artifacts/v2 (python -m contrimap_ml.train_v2). The image also builds
# without them (CI does this); /api/health then reports models_loaded=false until a volume or
# CONTRIMAP_ARTIFACT_DIR provides them.

FROM node:20-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html vite.config.js tailwind.config.js postcss.config.js ./
COPY src ./src
ENV VITE_BASE=/
RUN npx vite build

FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# The pip bundled with the base image cannot resolve uvicorn[standard] against the other pins.
RUN pip install --no-cache-dir --upgrade pip
# CPU-only torch keeps the image small; inference needs no GPU.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements-ml.txt
# Pre-download the sentence embedder so containers start offline.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
COPY contrimap_ml ./contrimap_ml
# Optional inputs: the bracket globs let the build succeed when they are absent (README.md always matches).
COPY README.md artifacts* ./artifacts/
COPY README.md data/processed/corpus.parquet* ./data/processed/
COPY --from=frontend /app/dist ./dist
ENV CONTRIMAP_SERVE_FRONTEND=1 CONTRIMAP_DEVICE=cpu PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/api/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "contrimap_ml.api:app", "--host", "0.0.0.0", "--port", "8001"]
