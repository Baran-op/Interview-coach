import react from '@vitejs/plugin-react'
import { spawn, type ChildProcess } from 'node:child_process'
import { createReadStream, existsSync, readFileSync } from 'node:fs'
import { connect } from 'node:net'
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

// `npm run dev` also starts the backend (uvicorn from ../.venv on :8000) and stops it on exit.
// Skipped when something already listens on :8000 (a backend you started by hand) or NO_BACKEND=1.
const repoRoot = join(import.meta.dirname, '..')
const BACKEND_PORT = 8000
const g = globalThis as { __backend?: ChildProcess }

function portInUse(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const sock = connect(port, '127.0.0.1')
    sock.once('connect', () => (sock.destroy(), resolve(true)))
    sock.once('error', () => resolve(false))
  })
}

function backend(): Plugin {
  return {
    name: 'start-backend',
    apply: 'serve',
    async configureServer() {
      if (process.env.NO_BACKEND === '1' || g.__backend) return // a config reload keeps the running backend
      if (await portInUse(BACKEND_PORT)) {
        console.log(`[backend] something is already running on :${BACKEND_PORT}, not starting another`)
        return
      }
      const python = join(repoRoot, '.venv/bin/python')
      if (!existsSync(python)) {
        console.warn('[backend] .venv not found: create it (see README, Setup) or start the backend by hand')
        return
      }
      const child = spawn(python, ['-m', 'uvicorn', 'backend.main:app', '--port', String(BACKEND_PORT)], {
        cwd: repoRoot,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONUNBUFFERED: '1' },
      })
      g.__backend = child
      const relay = (out: NodeJS.WriteStream) => (chunk: Buffer) => {
        for (const line of chunk.toString().split('\n')) if (line.trim()) out.write(`[backend] ${line}\n`)
      }
      child.stdout?.on('data', relay(process.stdout))
      child.stderr?.on('data', relay(process.stderr))
      child.on('exit', (code, signal) => {
        g.__backend = undefined
        console.log(`[backend] stopped (${signal ?? `exit code ${code}`})`)
      })
      const stop = () => {
        if (g.__backend && g.__backend.exitCode === null) g.__backend.kill('SIGTERM')
      }
      process.once('exit', stop)
      for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP'] as const) process.once(sig, () => (stop(), process.exit()))
    },
  }
}

// The backend runs on :8000. Proxying /api avoids CORS setup.
export default defineConfig({
  plugins: [react(), vadAssets(), backend()],
  server: {
    port: 5173,
    host: '127.0.0.1', // IPv4 only, local machine only (the app has no login)
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
