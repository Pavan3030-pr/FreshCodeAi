"""Deployment readiness: `python scripts/deploycheck.py` (reads .env / environment). Exit code 1 on any FAIL."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings  # noqa: E402
from app.core.config_check import check, exit_code  # noqa: E402

results = check(settings)
for level, cid, msg in results:
    print(f"{level:<5} {cid:<14} {msg}")
print(f"\nEnvironment: {settings.app_env} · {sum(1 for r in results if r[0] == 'OK')} ok, {sum(1 for r in results if r[0] == 'WARN')} warning(s), {sum(1 for r in results if r[0] == 'FAIL')} failure(s)")
sys.exit(exit_code(results))
