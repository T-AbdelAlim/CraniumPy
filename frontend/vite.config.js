import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // lets `npm run dev` hit the real FastAPI backend (desktop/app.py's
    // uvicorn instance) without any CORS config - app code just fetches
    // root-absolute paths like /api/sessions, same as it will once served
    // through FastAPI's own StaticFiles mount in every other run mode.
    proxy: { '/api': 'http://127.0.0.1:8734' },
  },
})
