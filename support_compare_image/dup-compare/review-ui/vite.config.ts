/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// In dev the API is the FastAPI review server (uvicorn backend.main:app --port 8000).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/review/': 'http://127.0.0.1:8000' } },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.ts',
  },
})
