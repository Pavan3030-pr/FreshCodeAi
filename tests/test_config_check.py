import dataclasses
import socket

from app.config import settings
from app.core.config_check import check, exit_code


def resolver(ip):
    def r(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    return r


def levels(s, ip="93.184.216.34"):
    return {cid: lvl for lvl, cid, _ in check(s, resolver=resolver(ip))}


def prod(**kw):
    base = dict(app_env="production", bifrost_base_url="https://gateway.example/v1", bifrost_api_key="k", tavily_api_key="t", cookie_secure=True,
                trust_proxy=True, runner_mode="docker", allow_registration=False, db_path="/var/lib/freshcode/db.sqlite", daily_run_quota=100)
    base.update(kw)
    return dataclasses.replace(settings, **base)


def test_clean_production_configuration_passes():
    r = check(prod(), resolver=resolver("93.184.216.34"))
    assert exit_code(r) == 0 and not [x for x in r if x[0] == "FAIL"] and not [x for x in r if x[0] == "WARN"], r


def test_insecure_production_settings_fail_loudly():
    lv = levels(prod(cookie_secure=False, runner_mode="local"))
    assert lv["cookie_secure"] == "FAIL" and lv["runner"] == "FAIL"
    assert exit_code(check(prod(cookie_secure=False), resolver=resolver("93.184.216.34"))) == 1


def test_private_or_metadata_gateway_urls_are_rejected_in_production_only():
    assert levels(prod(bifrost_base_url="https://internal.example/v1"), "10.1.2.3")["bifrost_url"] == "FAIL"
    assert levels(prod(bifrost_base_url="http://169.254.169.254/v1"))["bifrost_url"] == "FAIL"
    dev = dataclasses.replace(settings, app_env="development", bifrost_base_url="http://localhost:8080/v1")
    assert levels(dev, "127.0.0.1")["bifrost_url"] == "OK"


def test_warnings_for_missing_keys_http_and_open_registration():
    lv = levels(prod(bifrost_api_key="", tavily_api_key="", allow_registration=True, trust_proxy=False, db_path="/tmp/x.db"))
    assert lv["bifrost_key"] == "WARN" and lv["tavily_key"] == "WARN" and lv["registration"] == "WARN" and lv["trust_proxy"] == "WARN" and lv["db_path"] == "WARN"
    assert levels(prod(bifrost_base_url="http://gateway.example/v1"))["bifrost_tls"] == "WARN"
