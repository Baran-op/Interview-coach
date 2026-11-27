# Contributing

Thanks for helping out. This is a local, single-user app (FastAPI backend, React + Vite frontend).

## Dev setup

Follow "One-time setup" in the [README](README.md). Then run the backend
(`uvicorn backend.main:app --port 8000 --reload`) and the frontend (`cd frontend && npm run dev`).

## Before opening a PR

```sh
cd frontend
npm run lint
npm run build      # type-checks with tsc, then builds
```

CI runs the same two commands. The backend needs Apple Silicon for the voice models, so CI
only checks that the Python files compile.

## Guidelines

- Keep PRs focused; describe what changed and why.
- Never commit `.env`, `data/`, or avatar `.glb` files (they are git-ignored).
- Keep it single-user and local: no features that route other people through one Claude subscription
- Bugs: open an issue with your macOS/chip, browser, and the `/health` output.
