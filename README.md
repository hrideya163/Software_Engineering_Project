# ContriMap

A static React + Vite frontend for exploring open-source contribution opportunities. It uses realistic mock data by default and is ready to connect to the backend through `VITE_API_URL`.

## Run

```bash
npm install
npm run dev
npm run build
```

Copy `.env.example` to `.env` and set `VITE_API_URL` when the backend is available. The API modules keep endpoint paths isolated from the UI.
