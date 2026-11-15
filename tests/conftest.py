import os
import sys
import tempfile
from pathlib import Path

# Hermetic: a developer's local .env must never change test behaviour (load_dotenv does not override existing vars).
for key, value in {"APP_ENV": "development", "ENABLE_TEST_RUNNER": "1", "APP_ACCESS_TOKEN": "", "BIFROST_API_KEY": "",
                   "TAVILY_API_KEY": "", "TRUST_PROXY": "0", "RATE_LIMIT_PER_MINUTE": "10000", "HEAVY_RATE_LIMIT_PER_MINUTE": "1000",
                   "CACHE_TTL_SECONDS": "900", "DB_PATH": str(Path(tempfile.gettempdir()) / "freshcode-tests.db")}.items():
    os.environ[key] = value
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib.util  # noqa: E402

if importlib.util.find_spec("fastapi") is None or importlib.util.find_spec("pydantic") is None:
    # Offline sandbox only: tiny stand-ins so routes/middleware/auth can still be exercised. Real installs use the real packages.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
