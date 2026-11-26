import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nest_api  # noqa: E402
import nest_thermostat  # noqa: E402


class FakeNotices(dict):
    def delete(self, key):
        self.pop(key, None)


class FakePoly:
    def __init__(self):
        self.Notices = FakeNotices()


class FakeCtrl:
    def __init__(self, tmp, params):
        self.persist_dir = str(tmp)
        self.poly = FakePoly()
        self.nest_params = params
        self.nest_access = None


class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def params(**kw):
    d = {"project_id": "proj", "client_id": "cid", "client_secret": "sec", "auth_code": ""}
    d.update(kw)
    return d


def test_conversions():
    assert nest_thermostat.c_to_f(20.0) == 68.0
    assert nest_thermostat.f_to_c(68) == 20.0
    assert nest_thermostat.to_celsius(68, 17, "CELSIUS") == 20.0
    assert nest_thermostat.to_celsius(21.5, 4, "FAHRENHEIT") == 21.5
    assert nest_thermostat.to_celsius(68, None, "FAHRENHEIT") == 20.0
    assert nest_thermostat.to_celsius(21, None, "CELSIUS") == 21.0


def test_node_address_is_short_and_stable():
    a = nest_api.node_address("enterprises/p/devices/abc")
    assert a == nest_api.node_address("enterprises/p/devices/abc")
    assert len(a) <= 14


def test_device_name_fallbacks():
    assert nest_api.device_name({"traits": {"sdm.devices.traits.Info": {"customName": "Hall"}}}) == "Hall"
    assert nest_api.device_name({"parentRelations": [{"displayName": "Living Room"}]}) == "Living Room"
    assert nest_api.device_name({}) == "Nest Thermostat"


def test_code_exchange_saves_refresh_token_and_caches(tmp_path, monkeypatch):
    posts = []

    def fake_post(url, data=None, timeout=None):
        posts.append(data)
        return FakeResp(200, {"access_token": "AT", "expires_in": 3599, "refresh_token": "RT"})

    monkeypatch.setattr(nest_api.requests, "post", fake_post)
    ctrl = FakeCtrl(tmp_path, params(auth_code="code1"))
    assert nest_api.get_access_token(ctrl) == "AT"
    assert posts[0]["grant_type"] == "authorization_code"
    with open(tmp_path / "nest_token.json") as f:
        assert json.load(f)["refresh_token"] == "RT"
    assert nest_api.get_access_token(ctrl) == "AT"
    assert len(posts) == 1


def test_missing_code_sets_notice(tmp_path):
    ctrl = FakeCtrl(tmp_path, params())
    assert nest_api.get_access_token(ctrl) is None
    assert "nest_auth" in ctrl.poly.Notices


def test_invalid_grant_forgets_token(tmp_path, monkeypatch):
    with open(tmp_path / "nest_token.json", "w") as f:
        json.dump({"client_id": "cid", "refresh_token": "OLD", "used_code": "c0"}, f)
    monkeypatch.setattr(nest_api.requests, "post",
                        lambda url, data=None, timeout=None: FakeResp(400, {"error": "invalid_grant"}))
    ctrl = FakeCtrl(tmp_path, params())
    assert nest_api.get_access_token(ctrl) is None
    with open(tmp_path / "nest_token.json") as f:
        assert "refresh_token" not in json.load(f)
    assert "nest_auth" in ctrl.poly.Notices


def test_used_code_is_not_retried(tmp_path, monkeypatch):
    with open(tmp_path / "nest_token.json", "w") as f:
        json.dump({"client_id": "cid", "used_code": "c1"}, f)
    calls = []
    monkeypatch.setattr(nest_api.requests, "post",
                        lambda url, data=None, timeout=None: calls.append(1) or FakeResp(200, {}))
    ctrl = FakeCtrl(tmp_path, params(auth_code="c1"))
    assert nest_api.get_access_token(ctrl) is None
    assert calls == []
