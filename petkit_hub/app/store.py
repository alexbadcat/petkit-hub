"""Persistent config store (accounts + plugin settings) in the add-on /data dir.

Managed through the Ingress UI, NOT static add-on options — the user adds/removes
accounts and toggles plugins at runtime.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("PETKIT_HUB_DATA", "/data"))
STORE_PATH = DATA_DIR / "store.json"

_lock = threading.RLock()

_DEFAULT: dict[str, Any] = {
    "accounts": [],          # [{id, email, password, region, timezone, enabled}]
    "plugins": {},           # {slug: {"enabled": bool}}
}


def _read() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return json.loads(json.dumps(_DEFAULT))
    try:
        data = json.loads(STORE_PATH.read_text("utf-8"))
    except Exception:
        return json.loads(json.dumps(_DEFAULT))
    for k, v in _DEFAULT.items():
        data.setdefault(k, json.loads(json.dumps(v)))
    return data


def _write(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(STORE_PATH)


# --- accounts -----------------------------------------------------------------
def list_accounts(redact: bool = True) -> list[dict]:
    with _lock:
        accs = _read()["accounts"]
    if redact:
        accs = [{**a, "password": "••••••" if a.get("password") else ""} for a in accs]
    return accs


def get_account(acc_id: str) -> dict | None:
    with _lock:
        for a in _read()["accounts"]:
            if a["id"] == acc_id:
                return a
    return None


def add_account(email: str, password: str, region: str = "UA",
                timezone: str = "Europe/Kyiv") -> dict:
    acc = {
        "id": uuid.uuid4().hex[:8],
        "email": email,
        "password": password,
        "region": region or "UA",
        "timezone": timezone or "Europe/Kyiv",
        "enabled": True,
    }
    with _lock:
        data = _read()
        data["accounts"].append(acc)
        _write(data)
    return acc


def update_account(acc_id: str, **changes) -> dict | None:
    with _lock:
        data = _read()
        for a in data["accounts"]:
            if a["id"] == acc_id:
                for k, v in changes.items():
                    if k == "password" and (v is None or v == "" or set(v) == {"•"}):
                        continue  # keep existing password on redacted submits
                    if k in ("email", "password", "region", "timezone", "enabled"):
                        a[k] = v
                _write(data)
                return a
    return None


def remove_account(acc_id: str) -> bool:
    with _lock:
        data = _read()
        n = len(data["accounts"])
        data["accounts"] = [a for a in data["accounts"] if a["id"] != acc_id]
        if len(data["accounts"]) != n:
            _write(data)
            return True
    return False


# --- plugins ------------------------------------------------------------------
def seed_from_options() -> None:
    """Seed a first account from add-on options (HA writes them to /data/options.json).

    Lets a user (or headless deploy) provide bootstrap_email/password/region without
    opening the UI. Only seeds when the store has no accounts yet.
    """
    opt = DATA_DIR / "options.json"
    if not opt.exists():
        return
    try:
        o = json.loads(opt.read_text("utf-8"))
    except Exception:
        return
    email = (o.get("bootstrap_email") or "").strip()
    pw = o.get("bootstrap_password") or ""
    if email and pw and not _read()["accounts"]:
        add_account(email, pw, o.get("bootstrap_region") or "UA",
                    o.get("bootstrap_timezone") or "Europe/Kyiv")


def plugin_enabled(slug: str, default: bool = True) -> bool:
    with _lock:
        return _read()["plugins"].get(slug, {}).get("enabled", default)


def set_plugin_enabled(slug: str, enabled: bool) -> None:
    with _lock:
        data = _read()
        data["plugins"].setdefault(slug, {})["enabled"] = bool(enabled)
        _write(data)
