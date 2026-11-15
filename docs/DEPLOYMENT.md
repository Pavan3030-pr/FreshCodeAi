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

## Running generated tests on a hosted deployment (opt-in)
`RUNNER_MODE=off` is the default in `render.yaml`, so the UI reports tests as "Not run - runner disabled". The Docker image includes
pytest, so `RUNNER_MODE=local` works for Python tasks (JavaScript tests also need Node.js, which the image does not include).

`local` executes model-generated code on the web server and is **not a sandbox**. Only enable it on a private deployment:
1. Create your admin account first, then set `ALLOW_REGISTRATION=0` so nobody else can sign in.
2. Set `RUNNER_MODE=local` in the Render dashboard (or in `render.yaml` if the service is managed by the blueprint) and redeploy.
3. For anything public, use `RUNNER_MODE=docker` on a host that provides a Docker socket instead.
