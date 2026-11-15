import socket

from app.core.errors import ValidationFailed
from app.core.security import (DUMMY_HASH, hash_password, new_token, normalize_email, redact, safe_equal, token_hash,
                               validate_outbound_url, validate_password, verify_password)


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValidationFailed:
        return True
    return False


def test_password_hash_roundtrip_and_uniqueness():
    h1, h2 = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert h1 != h2 and h1.startswith("scrypt$") and "correct" not in h1
    assert verify_password("correct horse battery", h1) and not verify_password("wrong password!!", h1)
    assert not verify_password("x", "garbage") and not verify_password("x", "bcrypt$1$2$3$4$5")
    assert not verify_password("anything", DUMMY_HASH)


def test_password_policy():
    assert raises(validate_password, "short")
    assert raises(validate_password, "1234567890123")
    assert raises(validate_password, "password123")
    assert raises(validate_password, "aaaaaaaaaaaa")
    assert raises(validate_password, "ada@example.com", "ada@example.com")
    validate_password("a sufficiently long phrase")


def test_email_normalisation_and_validation():
    assert normalize_email("  Ada@Example.COM ") == "ada@example.com"
    for bad in ("", "no-at", "a@b", "a b@c.com", "@x.com", "a@" + "x" * 300 + ".com"):
        assert raises(normalize_email, bad), bad


def test_tokens_are_random_and_hashed_for_storage():
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 40 and token_hash(a) != a and len(token_hash(a)) == 64 and token_hash(a) == token_hash(a)
    assert safe_equal("abc", "abc") and not safe_equal("abc", "abd") and not safe_equal("", "x")


def test_redaction_masks_credentials_everywhere():
    s = redact("Authorization: Bearer abcdef123456789 key=tvly-SECRETVALUE123 sk-abcdefghijk1234 password=hunter2hunter Cookie: fc_session=AAAA.BBB; x", secrets_=["MYCONFIGKEY99"])
    for leaked in ("abcdef123456789", "SECRETVALUE123", "sk-abcdefghijk1234", "hunter2hunter", "AAAA.BBB"):
        assert leaked not in s, s
    assert "[redacted]" in s and "MYCONFIGKEY99" not in redact("boom MYCONFIGKEY99", secrets_=["MYCONFIGKEY99"])
    assert redact("nothing secret here") == "nothing secret here"


def fake_resolver(mapping):
    def resolve(host, port, proto=0):
        if host not in mapping:
            raise socket.gaierror("nx")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in mapping[host]]
    return resolve


def test_ssrf_blocks_private_loopback_metadata_and_bad_schemes():
    r = fake_resolver({"public.example": ["93.184.216.34"], "internal.example": ["10.0.0.5"], "mixed.example": ["93.184.216.34", "127.0.0.1"], "loop.example": ["127.0.0.1"], "v6.example": ["::1"]})
    assert validate_outbound_url("https://public.example/x", resolver=r) == "https://public.example/x"
    for bad in ("file:///etc/passwd", "ftp://public.example", "javascript:alert(1)", "https://user:pw@public.example/", "http://169.254.169.254/latest/meta-data",
                "https://internal.example/", "https://mixed.example/", "https://loop.example/", "https://v6.example/", "https://nx.example/", "http:///nohost"):
        assert raises(validate_outbound_url, bad, resolver=r), bad
    assert validate_outbound_url("http://localhost:8080/v1", allow_private=True)
