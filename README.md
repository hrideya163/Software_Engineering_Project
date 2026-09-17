# ContriMap

A React + Vite frontend, paired with an Express backend, for exploring open-source contribution opportunities. It uses realistic mock data by default; set `VITE_API_URL` to use the real backend instead. A separate Python ML service (`contrimap_ml/`) provides model-based issue predictions — see `requirements-ml.txt` and `run_pipeline.py`.

## Run the frontend

```bash
npm install
npm run dev
npm run build
```

Copy `.env.example` to `.env` and set `VITE_API_URL=http://localhost:8000/api` to use the real backend instead of mock data. The API modules in `src/api/` keep endpoint paths isolated from the UI.

## Run the backend

```bash
cd server
npm install
cp .env.example .env
npm run dev
```

The API listens on `http://localhost:8000/api` by default. See [server/README.md](server/README.md) for endpoint details and how to set up "Sign in with GitHub" and "Sign in with Google".
