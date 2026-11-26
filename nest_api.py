"""Small helper for Google's Smart Device Management (Nest) API.

Functions only (no classes). State lives on the controller object passed in
as `ctrl`: nest_params, nest_access, nest_nodes, persist_dir, poly.
Tokens are never logged. The refresh token is kept in persist/nest_token.json
(owner-only file permissions).
"""
import hashlib
import json
import os
import threading
import time

import requests
import udi_interface

LOGGER = udi_interface.LOGGER

TOKEN_URL = "https://www.googleapis.com/oauth2/v4/token"
SDM_BASE = "https://smartdevicemanagement.googleapis.com/v1"
REDIRECT_URI = "https://www.google.com"
THERMOSTAT_TYPE = "sdm.devices.types.THERMOSTAT"
TIMEOUT = 20

_lock = threading.RLock()


def _param(ctrl, key):
    return str((getattr(ctrl, "nest_params", None) or {}).get(key, "") or "").strip()


def _notice(ctrl, key, text):
    try:
        if text:
            ctrl.poly.Notices[key] = text
        else:
            ctrl.poly.Notices.delete(key)
    except Exception as e:  # deleting a missing notice is harmless
        LOGGER.debug("notice %s: %s", key, e)


def reset_cache(ctrl):
    ctrl.nest_access = None


def error_text(data):
    try:
        err = (data or {}).get("error")
        if isinstance(err, dict):
            return err.get("message") or err.get("status") or "unknown error"
        if err:
            return str(err)
    except Exception:
        pass
    return "no details"


# ---- saved sign-in ---------------------------------------------------------
def _token_path(ctrl):
    return os.path.join(getattr(ctrl, "persist_dir", None) or ".", "nest_token.json")


def _load_saved(ctrl):
    try:
        with open(_token_path(ctrl)) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        LOGGER.exception("Could not read saved Nest sign-in")
        return {}


def _save(ctrl, data):
    path = _token_path(ctrl)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _token_request(data):
    try:
        r = requests.post(TOKEN_URL, data=data, timeout=TIMEOUT)
    except requests.RequestException as e:
        LOGGER.error("Could not reach Google sign-in: %s", e)
        return None, {}
    try:
        body = r.json()
    except ValueError:
        body = {}
    return r.status_code, body


def get_access_token(ctrl, force=False):
    """Return a valid access token, or None (with a Notice explaining why)."""
    with _lock:
        now = time.time()
        cache = getattr(ctrl, "nest_access", None)
        if cache and not force and cache["exp"] - 60 > now:
            return cache["token"]

        client_id = _param(ctrl, "client_id")
        client_secret = _param(ctrl, "client_secret")
        saved = _load_saved(ctrl)
        refresh = saved.get("refresh_token") if saved.get("client_id") == client_id else None

        if not refresh:
            code = _param(ctrl, "auth_code")
            if not code:
                _notice(ctrl, "nest_auth", "Nest needs authorization: get a one-time code from Google "
                        "and paste it into the auth_code setting (see the setup notes).")
                return None
            if code == saved.get("used_code"):
                _notice(ctrl, "nest_auth", "The auth_code in settings was already used. "
                        "Get a fresh code from Google and paste it in.")
                return None
            status, body = _token_request({
                "client_id": client_id, "client_secret": client_secret, "code": code,
                "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI})
            if status == 200 and body.get("refresh_token") and body.get("access_token"):
                _save(ctrl, {"client_id": client_id, "refresh_token": body["refresh_token"],
                             "used_code": code})
                ctrl.nest_access = {"token": body["access_token"],
                                    "exp": now + float(body.get("expires_in", 3600))}
                _notice(ctrl, "nest_auth", None)
                LOGGER.info("Nest authorization completed")
                return ctrl.nest_access["token"]
            if status is not None:
                _save(ctrl, {"client_id": client_id, "used_code": code})
                _notice(ctrl, "nest_auth", "Google did not accept the auth_code (%s). Check the client "
                        "ID/secret and get a fresh code." % (body.get("error") or "HTTP %s" % status))
            return None

        status, body = _token_request({
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh, "grant_type": "refresh_token"})
        if status == 200 and body.get("access_token"):
            ctrl.nest_access = {"token": body["access_token"],
                                "exp": now + float(body.get("expires_in", 3600))}
            _notice(ctrl, "nest_auth", None)
            return ctrl.nest_access["token"]
        if status is not None and body.get("error") == "invalid_grant":
            _save(ctrl, {"client_id": client_id, "used_code": saved.get("used_code")})
            ctrl.nest_access = None
            _notice(ctrl, "nest_auth", "Google no longer accepts the saved sign-in (it may have expired "
                    "or been revoked). Get a new one-time code and paste it into auth_code.")
            return None
        LOGGER.warning("Could not refresh Nest access (HTTP %s): %s", status, error_text(body))
        return None


# ---- API calls -------------------------------------------------------------
def api_request(ctrl, method, path, body=None):
    """Call the SDM API. Returns (status_code or None, parsed_json_dict)."""
    for attempt in (0, 1):
        token = get_access_token(ctrl, force=(attempt == 1))
        if not token:
            return None, {}
        try:
            r = requests.request(
                method, SDM_BASE + path, json=body, timeout=TIMEOUT,
                headers={"Authorization": "Bearer " + token,
                         "Content-Type": "application/json"})
        except requests.RequestException as e:
            LOGGER.error("Could not reach Nest: %s", e)
            return None, {}
        if r.status_code == 401 and attempt == 0:
            continue
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code == 429:
            LOGGER.warning("Google says we are asking too often (HTTP 429)")
        return r.status_code, data
    return None, {}


def list_thermostats(ctrl):
    status, data = api_request(ctrl, "GET", "/enterprises/%s/devices" % _param(ctrl, "project_id"))
    if status != 200:
        if status is not None:
            LOGGER.error("Nest device list failed (HTTP %s): %s", status, error_text(data))
            _notice(ctrl, "nest_api", "Could not read your Nest devices (HTTP %s: %s). Check the "
                    "project_id and that the thermostat was shared when you authorized."
                    % (status, error_text(data)))
        return None
    _notice(ctrl, "nest_api", None)
    return [d for d in (data.get("devices") or []) if d.get("type") == THERMOSTAT_TYPE]


def device_name(device):
    traits = device.get("traits") or {}
    custom = (traits.get("sdm.devices.traits.Info") or {}).get("customName")
    if custom:
        return custom
    for rel in device.get("parentRelations") or []:
        if rel.get("displayName"):
            return rel["displayName"]
    return "Nest Thermostat"


def node_address(device_path):
    return "nt" + hashlib.sha1(device_path.encode()).hexdigest()[:10]


# ---- plugin-level actions --------------------------------------------------
def connect_and_discover(ctrl):
    """Sign in, list thermostats, create/update their nodes. Returns True on success."""
    from nest_thermostat import NestThermostat
    with _lock:
        missing = [k for k in ("project_id", "client_id", "client_secret") if not _param(ctrl, k)]
        if missing:
            _notice(ctrl, "nest_cfg", "Nest Thermostat needs these settings: %s" % ", ".join(missing))
            return False
        _notice(ctrl, "nest_cfg", None)

        devices = list_thermostats(ctrl)
        if devices is None:
            return False
        if not devices:
            _notice(ctrl, "nest_dev", "Signed in, but no thermostat was found. Re-run the Google "
                    "authorization and make sure the thermostat's permission is switched on.")
            return True
        _notice(ctrl, "nest_dev", None)

        nodes = getattr(ctrl, "nest_nodes", None)
        if nodes is None:
            nodes = {}
            ctrl.nest_nodes = nodes
        for dev in devices:
            path = dev.get("name")
            if not path:
                continue
            node = nodes.get(path)
            if node is None:
                addr = ctrl.poly.getValidAddress(node_address(path))
                name = ctrl.poly.getValidName(device_name(dev))
                node = NestThermostat(ctrl.poly, ctrl.address, addr, name, path, ctrl)
                ctrl.poly.addNode(node)
                nodes[path] = node
                LOGGER.info("Added Nest thermostat node %s (%s)", addr, name)
            node.update_from_traits(dev.get("traits"))
        return True


def refresh_all(ctrl):
    """One device-list call updates every known thermostat node."""
    nodes = getattr(ctrl, "nest_nodes", None) or {}
    if not nodes:
        return False
    with _lock:
        devices = list_thermostats(ctrl)
        if devices is None:
            return False
        for dev in devices:
            node = nodes.get(dev.get("name"))
            if node is not None:
                node.update_from_traits(dev.get("traits"))
        return True
