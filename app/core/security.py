"""Security primitives (stdlib only): password hashing, tokens, CSRF, secret redaction, SSRF-safe URL validation."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import re
import secrets
import socket
from typing import Iterable, Optional
from urllib.parse import urlparse

from app.core.errors import ValidationFailed

# ---------- passwords (scrypt) ----------
_N, _R, _P = 2 ** 14, 8, 1
_COMMON = frozenset("""password password1 password123 passw0rd qwerty123 letmein123 welcome123 admin12345 iloveyou123 123456789 1234567890
qwertyuiop changeme123 freshcode123 11111111 00000000 abc123456""".split())


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password("freshcode-dummy-password")  # verified against when the account does not exist (timing parity)


def validate_password(password: str, email: str = "") -> None:
    if len(password) < 10:
        raise ValidationFailed("Password must be at least 10 characters.")
    if len(password) > 200:
        raise ValidationFailed("Password is too long.")
    if password.isdigit() or password.lower() in _COMMON:
        raise ValidationFailed("That password is too easy to guess.")
    if email and password.lower() == email.lower():
        raise ValidationFailed("Password must differ from your email.")
    if len(set(password)) < 5:
        raise ValidationFailed("Password needs more variety.")


_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$")


def normalize_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL.match(e):
        raise ValidationFailed("Enter a valid email address.")
    return e


# ---------- tokens ----------
def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    """Sessions are stored hashed, so a database leak does not leak live sessions."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").encode("utf-8"), (b or "").encode("utf-8"))


# ---------- secret redaction ----------
# (pattern, keep_prefix): when keep_prefix is True group(1) is a label to keep and the rest is masked.
_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/=]{8,}"), True),
    (re.compile(r"\btvly-[A-Za-z0-9_\-]{6,}"), False),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), False),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password|authorization|x-api-key)\s*[=:]\s*)[^\s,;'\"]{4,}"), True),
    (re.compile(r"(?i)(fc_session=)[^\s;]+"), True),
]


def redact(text: str, secrets_: Iterable[str] = ()) -> str:
    """Mask credentials in any string destined for logs or error messages."""
    out = str(text)
    for s in secrets_:
        if s and len(s) >= 6:
            out = out.replace(s, "[redacted]")
    for pat, keep in _PATTERNS:
        out = pat.sub((lambda m: m.group(1) + "[redacted]") if keep else "[redacted]", out)
    return out


# ---------- SSRF-safe outbound URL validation ----------
def _ip_is_public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified
                or (a.version == 6 and a.ipv4_mapped is not None and not _ip_is_public(str(a.ipv4_mapped))))


def validate_outbound_url(url: str, *, allow_private: bool = False, resolver=socket.getaddrinfo) -> str:
    """Reject non-http(s), credentials in URL, and hosts that resolve to private/loopback/link-local/metadata ranges."""
    p = urlparse(url or "")
    if p.scheme not in {"http", "https"}:
        raise ValidationFailed("Only http(s) URLs are allowed.")
    if not p.hostname:
        raise ValidationFailed("URL has no host.")
    if p.username or p.password:
        raise ValidationFailed("Credentials in URLs are not allowed.")
    host = p.hostname
    if host.lower() in {"metadata.google.internal", "metadata"} or host == "169.254.169.254":
        raise ValidationFailed("That host is blocked.")
    if allow_private:
        return url
    try:
        infos = resolver(host, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValidationFailed("Host could not be resolved.")
    ips = {i[4][0] for i in infos}
    if not ips or not all(_ip_is_public(ip) for ip in ips):
        raise ValidationFailed("URL resolves to a non-public address.")
    return url
