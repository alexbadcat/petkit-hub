# PetKit Hub — Home Assistant Add-on repository

A self-hosted **PetKit hub** that lives entirely inside Home Assistant as an **add-on**
(not a HACS integration). It talks to the PetKit cloud, runs a **plugin per device
family**, and publishes every device to Home Assistant via **MQTT discovery** — so
entities appear natively with zero extra code in HA.

> Background: the PetKit Pura Max 2 cannot be controlled locally without reflashing
> (its firmware pins the cloud TLS cert — proven by MITM test). So this hub takes the
> **cloud-API** route, but keeps everything inside HA and under your control.

## Install

1. Settings → Add-ons → Add-on Store → ⋮ → **Repositories** → add this repo's URL.
2. Install **PetKit Hub**, start it, open its panel (Ingress).
3. Add one or more PetKit **accounts** and enable the **plugins** you want.

## Architecture

```
petkit_hub/                  ← the add-on ("app")
  app/
    runtime.py    account manager + poll loop + command dispatch
    mqtt.py       HA MQTT discovery + state/command topics
    store.py      persistent /data store (accounts, plugin settings)
    plugins_base.py   Plugin API (Entity descriptors, base class, loader)
    plugins/
      puramax/    PetKit T4 litter-box family (first plugin)
    ui/           Ingress web UI = the plugin/account manager
```

Add a new device family = drop a new folder under `app/plugins/`.
