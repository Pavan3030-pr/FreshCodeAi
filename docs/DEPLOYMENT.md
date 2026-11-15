# Deployment

## Local
```bash
python3 -m venv .venv && source .venv/bin/activate     # Windows: py -m venv .venv ; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                                    # Windows: copy .env.example .env
uvicorn app.main:app --port 8000
```

## Docker
```bash
docker build -t freshcode-ai .
docker run -p 8000:8000 -v freshcode-data:/data --env-file .env -e RUNNER_MODE=off freshcode-ai
# or: docker compose up --build
```
The image runs as a non-root user, stores the database in `/data` (mount a volume), and has a `/api/v1/ready` health check.

## Production checklist
1. `APP_ENV=production`, serve over HTTPS (reverse proxy), `COOKIE_SECURE=1`, `TRUST_PROXY=1`.
2. Create your admin account, then set `ALLOW_REGISTRATION=0`.
3. Keep `RUNNER_MODE=off`, or build the runner image (`make runner-image`) and use `RUNNER_MODE=docker` on a Docker host (read docs/SECURITY.md).
4. Persistent volume for `DB_PATH`; schedule backups (docs/DATABASE.md).
5. `make deploycheck` must show no FAIL. `make audit` for dependency advisories.
6. Provide `BIFROST_*` and `TAVILY_API_KEY` through your platform's secret manager.

`render.yaml` is provided for Render (disk mounted at `/data`).
