import re
from pathlib import Path

from app.config import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_consistent_everywhere():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert f"v{APP_VERSION}" in html and set(re.findall(r"\?v=([\d.]+)", html)) == {APP_VERSION}
    assert f"v{APP_VERSION.rsplit('.', 1)[0]}" in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
    assert f"## v{APP_VERSION}" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_landing_versions_match():
    landing = (ROOT / "static" / "landing.html").read_text(encoding="utf-8")
    assert f"v{APP_VERSION}" in landing and set(re.findall(r"\?v=([\d.]+)", landing)) == {APP_VERSION}


def test_login_page_versions_match():
    login = (ROOT / "static" / "login.html").read_text(encoding="utf-8")
    assert set(re.findall(r"\?v=([\d.]+)", login)) == {APP_VERSION}
