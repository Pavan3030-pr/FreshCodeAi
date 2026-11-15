"""Dependency-light test runner: executes every tests/test_*.py function without pytest.

Used where pytest/fastapi/httpx cannot be installed. Modules that need missing packages are reported as SKIPPED
(never as passed). Real CI runs the full suite with pytest (see .github/workflows/ci.yml).
"""
import asyncio
import importlib.util
import inspect
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
import conftest  # noqa: F401  (hermetic environment)
sys.path.insert(0, str(ROOT))
passed = failed = 0
skipped_modules = []
for path in sorted((ROOT / "tests").glob("test_*.py")):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError as exc:
        skipped_modules.append((path.name, str(exc)))
        continue
    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        if not name.startswith("test_") or fn.__module__ != mod.__name__:
            continue
        try:
            if inspect.iscoroutinefunction(fn):
                asyncio.run(fn())
            else:
                fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"FAIL {path.name}::{name}")
            traceback.print_exc()
print(f"\n{passed} passed, {failed} failed, {len(skipped_modules)} module(s) skipped")
for name, why in skipped_modules:
    print(f"  SKIPPED {name}: {why}")
sys.exit(1 if failed else 0)
