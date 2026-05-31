"""Runtime: logs into each PetKit account, maps devices to plugins, publishes them
to Home Assistant via MQTT discovery, polls state, and dispatches commands.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import aiomqtt
from pypetkitapi.client import PetKitClient

from . import mqtt as M
from . import store
from .plugins_base import Entity, PetkitPlugin, discover_plugins
from .supervisor import mqtt_config

log = logging.getLogger("petkit_hub.runtime")


@dataclass
class DeviceCtx:
    account_id: str
    device_id: str
    plugin: PetkitPlugin
    meta: dict
    entities: dict[str, Entity]


@dataclass
class AccountCtx:
    acc_id: str
    email: str
    session: aiohttp.ClientSession
    client: PetKitClient
    devices: dict[str, DeviceCtx] = field(default_factory=dict)


class Runtime:
    def __init__(self, poll_interval: int = 60):
        self.plugins: dict[str, PetkitPlugin] = discover_plugins()
        self.poll_interval = poll_interval
        self._mqtt: aiomqtt.Client | None = None
        self._accounts: dict[str, AccountCtx] = {}
        self._reload = asyncio.Event()
        self._stop = asyncio.Event()
        # UI-facing status
        self.status: dict[str, Any] = {"mqtt": "down", "accounts": {}}

    # ---- lifecycle -----------------------------------------------------------
    def request_reload(self) -> None:
        self._reload.set()

    async def run(self) -> None:
        cfg = await mqtt_config()
        if not cfg:
            self.status["mqtt"] = "unavailable"
            log.error("no MQTT broker available; runtime idle (UI still works)")
            await self._stop.wait()
            return
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=cfg.host, port=cfg.port,
                    username=cfg.username, password=cfg.password,
                    identifier="petkit_hub",
                ) as client:
                    self._mqtt = client
                    self.status["mqtt"] = "connected"
                    log.info("MQTT connected to %s:%s", cfg.host, cfg.port)
                    await client.subscribe(M.command_subscription())
                    listener = asyncio.create_task(self._listen())
                    try:
                        await self._serve()
                    finally:
                        listener.cancel()
            except aiomqtt.MqttError as exc:
                self.status["mqtt"] = "reconnecting"
                log.warning("MQTT error: %s; retrying in 5s", exc)
                await asyncio.sleep(5)
            finally:
                self._mqtt = None

    async def _serve(self) -> None:
        """(Re)build accounts, then poll until a reload is requested."""
        while not self._stop.is_set():
            self._reload.clear()
            await self._sync_accounts()
            while not self._reload.is_set() and not self._stop.is_set():
                await self._poll_once()
                try:
                    await asyncio.wait_for(self._reload.wait(), timeout=self.poll_interval)
                except asyncio.TimeoutError:
                    pass

    # ---- accounts / discovery ------------------------------------------------
    async def _sync_accounts(self) -> None:
        wanted = {a["id"]: a for a in store.list_accounts(redact=False) if a.get("enabled", True)}

        # drop accounts no longer wanted
        for acc_id in list(self._accounts):
            if acc_id not in wanted:
                await self._teardown_account(acc_id)

        for acc_id, a in wanted.items():
            if acc_id in self._accounts:
                continue
            await self._setup_account(a)

    async def _setup_account(self, a: dict) -> None:
        st = self.status["accounts"].setdefault(a["id"], {})
        st.update(email=a["email"], state="connecting", devices=0, error=None)
        session = aiohttp.ClientSession()
        try:
            client = PetKitClient(
                username=a["email"], password=a["password"],
                region=a.get("region", "UA"), timezone=a.get("timezone", "Europe/Kyiv"),
                session=session,
            )
            await client.get_devices_data()
        except Exception as exc:  # noqa: BLE001
            await session.close()
            st.update(state="error", error=str(exc))
            log.error("account %s login failed: %s", a["email"], exc)
            return

        ctx = AccountCtx(acc_id=a["id"], email=a["email"], session=session, client=client)
        self._accounts[a["id"]] = ctx

        for dev_id, device in client.petkit_entities.items():
            plugin = self._match_plugin(device)
            if not plugin:
                continue
            if not store.plugin_enabled(plugin.slug):
                continue
            try:
                ents = {e.key: e for e in plugin.entities(device, client.petkit_entities)}
                meta = plugin.device_meta(device)
            except Exception as exc:  # noqa: BLE001
                log.warning("plugin %s entities() failed for %s: %s", plugin.slug, dev_id, exc)
                continue
            dctx = DeviceCtx(a["id"], str(dev_id), plugin, meta, ents)
            ctx.devices[str(dev_id)] = dctx
            await self._publish_discovery(dctx)
            await self._publish_availability(dctx.device_id, True)
            await self._publish_state(ctx, dctx)

        st.update(state="online", devices=len(ctx.devices), error=None)
        log.info("account %s online: %d device(s) published", a["email"], len(ctx.devices))

    async def _teardown_account(self, acc_id: str) -> None:
        ctx = self._accounts.pop(acc_id, None)
        if not ctx:
            return
        for dctx in ctx.devices.values():
            await self._publish_availability(dctx.device_id, False)
        try:
            await ctx.session.close()
        except Exception:  # noqa: BLE001
            pass
        self.status["accounts"].get(acc_id, {}).update(state="offline", devices=0)

    def _match_plugin(self, device: Any) -> PetkitPlugin | None:
        for p in self.plugins.values():
            try:
                if p.match(device):
                    return p
            except Exception:  # noqa: BLE001
                continue
        return None

    # ---- publish -------------------------------------------------------------
    async def _publish_discovery(self, dctx: DeviceCtx) -> None:
        if not self._mqtt:
            return
        for ent in dctx.entities.values():
            topic, payload = M.discovery_payload(dctx.device_id, dctx.meta, ent)
            await self._mqtt.publish(topic, json.dumps(payload), retain=True)

    async def _publish_availability(self, device_id: str, online: bool) -> None:
        if not self._mqtt:
            return
        await self._mqtt.publish(M.availability_topic(device_id),
                                 "online" if online else "offline", retain=True)

    async def _publish_state(self, ctx: AccountCtx, dctx: DeviceCtx) -> None:
        if not self._mqtt:
            return
        device = ctx.client.petkit_entities.get(int(dctx.device_id)) \
            or ctx.client.petkit_entities.get(dctx.device_id)
        if device is None:
            return
        state: dict[str, Any] = {}
        for key, ent in dctx.entities.items():
            if ent.value is None:
                continue
            try:
                v = ent.value(device)
            except Exception as exc:  # noqa: BLE001
                log.debug("getter %s failed: %s", key, exc)
                continue
            if isinstance(v, bool):
                v = "ON" if v else "OFF"
            state[key] = v
        await self._mqtt.publish(M.state_topic(dctx.device_id), json.dumps(state, default=str), retain=True)

    async def _poll_once(self) -> None:
        for ctx in list(self._accounts.values()):
            try:
                await ctx.client.get_devices_data()
            except Exception as exc:  # noqa: BLE001
                log.warning("poll for %s failed: %s", ctx.email, exc)
                self.status["accounts"].get(ctx.acc_id, {}).update(state="error", error=str(exc))
                continue
            self.status["accounts"].get(ctx.acc_id, {}).update(state="online", error=None)
            for dctx in ctx.devices.values():
                await self._publish_availability(dctx.device_id, True)
                await self._publish_state(ctx, dctx)

    # ---- commands ------------------------------------------------------------
    async def _listen(self) -> None:
        assert self._mqtt
        async for msg in self._mqtt.messages:
            parsed = M.parse_command_topic(str(msg.topic))
            if not parsed:
                continue
            device_id, key = parsed
            payload = msg.payload.decode() if isinstance(msg.payload, (bytes, bytearray)) else str(msg.payload)
            asyncio.create_task(self._dispatch(device_id, key, payload))

    async def _dispatch(self, device_id: str, key: str, payload: str) -> None:
        for ctx in self._accounts.values():
            dctx = ctx.devices.get(device_id)
            if not dctx:
                continue
            ent = dctx.entities.get(key)
            if not ent or ent.command is None:
                log.warning("no command for %s/%s", device_id, key)
                return
            device = ctx.client.petkit_entities.get(int(device_id)) \
                or ctx.client.petkit_entities.get(device_id)
            try:
                log.info("command %s/%s payload=%r", device_id, key, payload)
                await ent.command(ctx.client, device, payload)
            except Exception as exc:  # noqa: BLE001
                log.error("command %s/%s failed: %s", device_id, key, exc)
                return
            # optimistic refresh
            try:
                await ctx.client.get_devices_data()
                await self._publish_state(ctx, dctx)
            except Exception:  # noqa: BLE001
                pass
            return
        log.warning("command for unknown device %s", device_id)

    async def shutdown(self) -> None:
        self._stop.set()
        self._reload.set()
        for acc_id in list(self._accounts):
            await self._teardown_account(acc_id)
