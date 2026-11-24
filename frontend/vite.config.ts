import react from '@vitejs/plugin-react'
import { createReadStream, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { defineConfig, type Plugin } from 'vite'

// Files the voice activity detector loads at runtime (Silero model, audio
// worklet, onnxruntime WASM). Served at /vad/ straight from node_modules so it
// all works offline. Not in public/: Vite's dev server won't let onnxruntime
// import() an .mjs from there.
const vadDist = join(import.meta.dirname, 'node_modules/@ricky0123/vad-web/dist')
const ortDist = join(import.meta.dirname, 'node_modules/onnxruntime-web/dist')
const VAD_FILES: Record<string, string> = {
  'vad.worklet.bundle.min.js': join(vadDist, 'vad.worklet.bundle.min.js'),
  'silero_vad_v5.onnx': join(vadDist, 'silero_vad_v5.onnx'),
  'ort-wasm-simd-threaded.wasm': join(ortDist, 'ort-wasm-simd-threaded.wasm'),
  'ort-wasm-simd-threaded.mjs': join(ortDist, 'ort-wasm-simd-threaded.mjs'),
}
const MIME: Record<string, string> = {
  js: 'text/javascript',
  mjs: 'text/javascript',
  wasm: 'application/wasm',
  onnx: 'application/octet-stream',
}

function vadAssets(): Plugin {
  return {
    name: 'vad-assets',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? '').split('?')[0]
        if (!path.startsWith('/vad/')) return next()
        const file = VAD_FILES[path.slice('/vad/'.length)]
        if (!file) {
          res.statusCode = 404
          return res.end()
        }
        res.setHeader('Content-Type', MIME[file.split('.').pop() ?? ''] ?? 'application/octet-stream')
        createReadStream(file).pipe(res)
      })
    },
    generateBundle() {
      for (const [name, file] of Object.entries(VAD_FILES)) {
        this.emitFile({ type: 'asset', fileName: `vad/${name}`, source: readFileSync(file) })
      }
    },
  }
}

// The backend runs on :8000. Proxying /api avoids CORS setup.
export default defineConfig({
  plugins: [react(), vadAssets()],
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
