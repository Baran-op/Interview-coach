import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend runs on :8000. Proxying /api avoids CORS setup.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
