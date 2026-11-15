"""Static accessibility + consistency checks on the UI (no browser needed): WCAG contrast and CSS/HTML/JS class coverage."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
ALL_CSS = CSS + (STATIC / "landing.css").read_text(encoding="utf-8") + (STATIC / "auth.css").read_text(encoding="utf-8")
LOGIN = (STATIC / "login.html").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
LANDING = (STATIC / "landing.html").read_text(encoding="utf-8")
JS = "".join((STATIC / f).read_text(encoding="utf-8") for f in ("app.js", "landing.js", "account.js", "auth.js"))


def _tokens(block: str) -> dict:
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block))


def _themes():
    return {"light": _tokens(re.search(r":root\{(.*?)\n\}", CSS, re.S).group(0))}


def _lum(hexcolor: str) -> float:
    r, g, b = (int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


PAIRS = [("muted", "lavender"), ("muted", "lilac"), ("muted", "sand"), ("muted", "good-soft"), ("muted", "peach-soft"), ("muted", "lilac-soft"), ("muted", "mint-soft"),
         ("plum", "lilac"), ("plum", "lavender"), ("plum", "peach"), ("plum", "sand"), ("brand-d", "lavender"), ("brand-d", "brand-soft"), ("brand-d", "panel"), ("good", "peach-soft"), ("warn", "peach-soft"),
         ("bad", "peach-soft"), ("tk-c", "code-bg"), ("tk-s", "code-bg"), ("tk-k", "code-bg"), ("tk-n", "code-bg"), ("tk-f", "code-bg"), ("ink", "lavender"), ("ink", "peach-soft"), ("ink", "good-soft"), ("peach", "plum"),
         ("ink", "bg"), ("ink", "panel"), ("ink", "panel2"), ("muted", "bg"), ("muted", "panel"), ("muted", "panel2"), ("muted", "side"),
         ("brand", "panel"), ("brand", "brand-soft"), ("brand", "bg"), ("on-brand", "brand"), ("on-brand", "brand-d"), ("good", "good-soft"),
         ("bad", "bad-soft"), ("warn", "warn-soft"), ("blue", "blue-soft"), ("code-ink", "code-bg"), ("good", "panel"), ("warn", "panel"), ("bad", "panel"), ("peach-ink", "peach-soft"), ("peach-ink", "panel")]


def test_text_contrast_meets_wcag_aa_on_every_surface():
    failures = []
    for name, t in _themes().items():
        for fg, bg in PAIRS:
            ratio = contrast(t[fg], t[bg])
            if ratio < 4.5:
                failures.append(f"{name}: {fg} on {bg} = {ratio:.2f}")
    assert not failures, failures


def test_every_class_used_in_html_and_js_has_a_css_rule():
    used = set()
    for m in re.finditer(r'class="([^"$]+)"', HTML + LANDING + LOGIN + JS):
        used.update(t for t in m.group(1).split() if re.fullmatch(r"[A-Za-z][\w-]*", t))  # skip fragments of JS string concatenation
    for m in re.finditer(r"class=\\?\"([^\"$\\]+)", JS):
        used.update(t for t in m.group(1).split() if re.fullmatch(r"[A-Za-z][\w-]*", t))
    dynamic_ok = {"landing", "stale", "contra", "active", "done", "error", "good", "warn", "bad", "muted", "brand", "purple", "green", "blue", "amber", "info", "show", "is-busy", "big", "primary", "mono", "rich", "stack", "hidden", "grow", "pills", "logo", "meta", "sources", "source", "list", "view"}
    defined = set(re.findall(r"\.([a-zA-Z][\w-]*)", ALL_CSS))
    missing = sorted(c for c in used if c not in defined and c not in dynamic_ok)
    assert not missing, missing


def test_css_is_well_formed():
    assert CSS.count("{") == CSS.count("}") and ALL_CSS.count("{") == ALL_CSS.count("}")
    assert "@media(prefers-reduced-motion:reduce)" in CSS and ":focus-visible" in CSS and "[hidden]" in CSS


def test_html_a11y_basics():
    assert 'lang="en"' in HTML and "skip-link" in HTML and 'id="main"' in HTML
    views = len(re.findall(r'<section class="view"', HTML))
    assert views >= 9 and len(re.findall(r"<h1\b", HTML)) == views  # one h1 per view, only one view visible at a time
    for m in re.finditer(r'<(textarea|input|select)\b([^>]*)>', HTML):
        attrs = m.group(2)
        ident = re.search(r'id="([^"]+)"', attrs)
        if ident and 'type="checkbox"' not in attrs and 'type="range"' not in attrs and 'type="hidden"' not in attrs:
            assert re.search(rf'for="{ident.group(1)}"', HTML) or "aria-label" in attrs, f"unlabelled control #{ident.group(1)}"
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", HTML, re.S):
        assert re.sub(r"<[^>]+>", "", m.group(2)).strip() or "aria-label" in m.group(1)


def test_landing_page_a11y_and_structure():
    assert 'lang="en"' in LANDING and "skip-link" in LANDING and len(re.findall(r"<h1\b", LANDING)) == 1
    for section in ("problem", "how", "bifrost", "tavily", "compression", "verification", "freshness", "evidence", "roi", "security", "architecture", "faq"):
        assert f'id="{section}"' in LANDING, section
    assert 'href="/app#demo"' in LANDING and 'href="/login#signup"' in LANDING and 'href="/login"' in LANDING
    for m in re.finditer(r"<(input|select|textarea)\b([^>]*)>", LANDING):
        ident = re.search(r'id="([^"]+)"', m.group(2))
        assert ident and re.search(rf'for="{ident.group(1)}"', LANDING), m.group(0)
    assert not re.search(r"\son[a-z]+=\"", LANDING) and not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", LANDING)


def test_light_only_no_dark_mode_anywhere():
    for page in (HTML, LANDING, LOGIN, CSS, ALL_CSS, JS):
        assert "data-theme" not in page and "☾" not in page and "prefers-color-scheme" not in page
    for page in (HTML, LANDING, LOGIN):
        assert 'content="light"' in page and "theme.js" in page


def test_palette_is_tinted_not_white():
    t = _themes()["light"]
    for name in ("bg", "panel", "panel2", "side", "code-bg"):
        assert t[name].lower() not in ("#ffffff", "#fff"), name
    for name, expected in {"lavender": "#e9ddf7", "lilac": "#dccbf0", "violet": "#8062a8", "plum": "#49365f", "peach": "#f5d7c6", "apricot": "#eec1a5", "sage": "#d5e5d3", "mint": "#c5dfd0", "sand": "#ede2d2", "cream": "#f3ebdd"}.items():
        assert t[name].lower() == expected, name


def test_three_region_agent_workspace_and_eleven_stages():
    assert HTML.count('data-stage="') == 11 and all(r in HTML for r in ("ws-config", "ws-main", "ws-exec"))


def test_login_page_a11y_and_security_basics():
    assert 'lang="en"' in LOGIN and "skip-link" in LOGIN and len(re.findall(r"<h1\b", LOGIN)) == 1
    assert LOGIN.index("theme.js") < LOGIN.index("style.css") and "Google" not in LOGIN and "GitHub" not in LOGIN
    for m in re.finditer(r"<input\b([^>]*)>", LOGIN):
        ident = re.search(r'id="([^"]+)"', m.group(1))
        assert ident and re.search(rf'for="{ident.group(1)}"', LOGIN), m.group(0)
    for needed in ('autocomplete="current-password"', 'autocomplete="new-password"', 'autocomplete="username"', 'role="alert"', 'role="tablist"'):
        assert needed in LOGIN, needed
    assert not re.search(r"\son[a-z]+=\"", LOGIN) and not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", LOGIN)
