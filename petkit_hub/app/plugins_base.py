"""Plugin API for PetKit Hub.

A plugin handles one PetKit *device family* (identified by ``device_type``) and
declares a flat list of :class:`Entity` descriptors per device. The runtime turns
those into MQTT-discovery configs, publishes state by calling each entity's
``value`` getter, and dispatches incoming commands to each entity's ``command``.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger("petkit_hub.plugins")

# HA discovery components we support
COMPONENTS = {"sensor", "binary_sensor", "button", "switch", "select", "number", "text"}


@dataclass
class Entity:
    """One Home Assistant entity exposed for a device."""
    key: str                       # stable per-device id, e.g. "litter_percent"
    name: str                      # friendly name
    component: str                 # one of COMPONENTS
    device_class: Optional[str] = None
    unit: Optional[str] = None
    icon: Optional[str] = None
    options: Optional[list[str]] = None      # for select
    category: Optional[str] = None           # "diagnostic" | "config" | None
    extra: dict = field(default_factory=dict)  # extra discovery fields (min/max/step, payload_on, …)
    # state: device -> value (None ⇒ entity has no state, e.g. a button)
    value: Optional[Callable[[Any], Any]] = None
    # command: async (client, device, payload) -> Any (for button/switch/select/number/text)
    command: Optional[Callable[..., Awaitable[Any]]] = None

    def __post_init__(self):
        if self.component not in COMPONENTS:
            raise ValueError(f"unknown component {self.component!r} for entity {self.key!r}")


class PetkitPlugin:
    """Base class. Subclass per device family and expose a module-level ``PLUGIN``."""
    slug: str = "base"
    name: str = "Base"
    handles: set[str] = set()      # device_type strings this plugin owns, e.g. {"t4"}

    # --- device identification -------------------------------------------------
    @staticmethod
    def device_type(device: Any) -> Optional[str]:
        nfo = getattr(device, "device_nfo", None)
        return getattr(nfo, "device_type", None) if nfo else None

    @staticmethod
    def device_id(device: Any) -> Optional[int]:
        nfo = getattr(device, "device_nfo", None)
        return getattr(nfo, "device_id", None) if nfo else getattr(device, "id", None)

    def match(self, device: Any) -> bool:
        return (self.device_type(device) or "").lower() in self.handles

    def device_meta(self, device: Any) -> dict:
        """HA device-registry block shared by all of this device's entities."""
        nfo = getattr(device, "device_nfo", None)
        model = getattr(nfo, "modele_name", None) or getattr(nfo, "device_type", None)
        return {
            "identifiers": [f"petkit_{self.device_id(device)}"],
            "name": getattr(device, "name", None) or f"PetKit {self.device_id(device)}",
            "manufacturer": "PetKit",
            "model": model,
            "sw_version": str(getattr(device, "firmware", "") or ""),
        }

    # --- entities --------------------------------------------------------------
    def entities(self, device: Any, entities_map: dict | None = None) -> list[Entity]:
        """Return entity descriptors. ``entities_map`` is the account's live
        {id: device} dict (mutated in place each poll) for cross-device reads."""
        raise NotImplementedError


def discover_plugins() -> dict[str, PetkitPlugin]:
    """Import every ``app.plugins.<name>.plugin`` exposing ``PLUGIN`` -> {slug: plugin}."""
    import app.plugins as pkg

    out: dict[str, PetkitPlugin] = {}
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.ispkg is False:
            continue
        try:
            m = importlib.import_module(f"app.plugins.{mod.name}.plugin")
        except Exception as exc:  # noqa: BLE001
            log.warning("plugin %s failed to import: %s", mod.name, exc)
            continue
        plugin = getattr(m, "PLUGIN", None)
        if isinstance(plugin, PetkitPlugin):
            out[plugin.slug] = plugin
            log.info("loaded plugin %s (handles %s)", plugin.slug, sorted(plugin.handles))
    return out
