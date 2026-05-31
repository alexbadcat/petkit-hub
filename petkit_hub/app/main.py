"""FastAPI app: Ingress UI (the account/plugin manager) + REST API, and it owns
the background Runtime that bridges PetKit ⇄ Home Assistant over MQTT.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import store
from .runtime import Runtime

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("petkit_hub")

UI_DIR = Path(__file__).parent / "ui"
runtime: Runtime | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global runtime
    store.seed_from_options()
    runtime = Runtime()
    task = asyncio.create_task(runtime.run())
    log.info("PetKit Hub started (%d plugins)", len(runtime.plugins))
    try:
        yield
    finally:
        await runtime.shutdown()
        task.cancel()


app = FastAPI(title="PetKit Hub", lifespan=lifespan)


# --- models -------------------------------------------------------------------
class AccountIn(BaseModel):
    email: str
    password: str = ""
    region: str = "UA"
    timezone: str = "Europe/Kyiv"
    enabled: bool = True


class PluginIn(BaseModel):
    enabled: bool


# --- API ----------------------------------------------------------------------
@app.get("/api/status")
async def status():
    return {
        "mqtt": runtime.status.get("mqtt") if runtime else "down",
        "accounts": runtime.status.get("accounts", {}) if runtime else {},
        "plugins": [
            {"slug": p.slug, "name": p.name, "handles": sorted(p.handles),
             "enabled": store.plugin_enabled(p.slug)}
            for p in (runtime.plugins.values() if runtime else [])
        ],
    }


@app.get("/api/accounts")
async def accounts():
    return store.list_accounts(redact=True)


@app.post("/api/accounts")
async def add_account(a: AccountIn):
    if not a.email or not a.password:
        raise HTTPException(400, "email and password required")
    acc = store.add_account(a.email, a.password, a.region, a.timezone)
    _reload()
    return {"id": acc["id"]}


@app.put("/api/accounts/{acc_id}")
async def update_account(acc_id: str, a: AccountIn):
    upd = store.update_account(
        acc_id, email=a.email, password=a.password, region=a.region,
        timezone=a.timezone, enabled=a.enabled,
    )
    if not upd:
        raise HTTPException(404, "account not found")
    _reload()
    return {"ok": True}


@app.delete("/api/accounts/{acc_id}")
async def delete_account(acc_id: str):
    if not store.remove_account(acc_id):
        raise HTTPException(404, "account not found")
    _reload()
    return {"ok": True}


@app.get("/api/plugins")
async def plugins():
    return [
        {"slug": p.slug, "name": p.name, "handles": sorted(p.handles),
         "enabled": store.plugin_enabled(p.slug)}
        for p in (runtime.plugins.values() if runtime else [])
    ]


@app.post("/api/plugins/{slug}")
async def set_plugin(slug: str, p: PluginIn):
    store.set_plugin_enabled(slug, p.enabled)
    _reload()
    return {"ok": True}


def _reload():
    if runtime:
        runtime.request_reload()


# --- UI (Ingress) -------------------------------------------------------------
@app.get("/")
async def index():
    idx = UI_DIR / "index.html"
    if idx.exists():
        return FileResponse(idx)
    return JSONResponse({"service": "petkit_hub", "ui": "missing"})


if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8099")),
                log_level=os.environ.get("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
