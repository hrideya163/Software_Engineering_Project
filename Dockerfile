# Single image: built React frontend + FastAPI backend + trained artifacts.
#   docker build -t contrimap .
#   docker run -p 8001:8001 --env-file .env contrimap      -> http://localhost:8001
# Requires artifacts/v2 (python -m contrimap_ml.train_v2) in the build context.

FROM node:20-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js tailwind.config.js postcss.config.js ./
COPY src ./src
ENV VITE_BASE=/
RUN npx vite build

FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# CPU-only torch keeps the image small; inference needs no GPU.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements-ml.txt
# Pre-download the sentence embedder so containers start offline.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
COPY contrimap_ml ./contrimap_ml
COPY artifacts/v2 ./artifacts/v2
COPY data/processed/corpus.parquet ./data/processed/corpus.parquet
COPY --from=frontend /app/dist ./dist
ENV CONTRIMAP_SERVE_FRONTEND=1 CONTRIMAP_DEVICE=cpu PYTHONUNBUFFERED=1
EXPOSE 8001
CMD ["uvicorn", "contrimap_ml.api:app", "--host", "0.0.0.0", "--port", "8001"]
