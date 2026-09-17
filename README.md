# ContriMap

A React + Vite frontend, paired with an Express backend, for exploring real open-source contribution opportunities. The backend pulls live repository and issue data from the GitHub API and layers heuristic difficulty/skill-match scoring on top. Without a backend running, the frontend falls back to realistic mock data automatically.

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

The API listens on `http://localhost:8000/api` by default. See [server/README.md](server/README.md) for endpoint details and how to raise GitHub's rate limit with a personal access token.
