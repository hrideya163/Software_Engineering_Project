import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Vercel serves the app from the domain root; only GitHub Pages needs the
  // '/ContriMap-website/' subpath, so switch based on Vercel's own build env var.
  // VITE_BASE overrides both (the Docker image serves the app from '/').
  base: process.env.VITE_BASE || (process.env.VERCEL ? '/' : '/ContriMap-website/')
})