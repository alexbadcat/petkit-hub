// PetKit Hub — Ingress manager UI. All fetches are relative so the HA ingress
// path prefix is honoured automatically.
const $ = (s, r = document) => r.querySelector(s);
const api = (p, opt) => fetch(p, opt).then(async r => {
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.status === 204 ? null : r.json();
});

function toast(msg, ms = 2600) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

const STATE = { ok: "pill--ok", online: "pill--ok", connected: "pill--ok",
                error: "pill--warn", reconnecting: "pill--warn",
                connecting: "pill--muted", offline: "pill--muted",
                down: "pill--muted", unavailable: "pill--warn" };

async function refresh() {
  let s;
  try { s = await api("api/status"); }
  catch (e) { $("#mqtt").className = "pill pill--warn"; $("#mqtt").textContent = "API error"; return; }

  const mp = $("#mqtt");
  mp.className = "pill " + (STATE[s.mqtt] || "pill--muted");
  mp.textContent = "MQTT: " + s.mqtt;

  // accounts
  const accs = await api("api/accounts");
  const acc = $("#accounts"); acc.innerHTML = "";
  if (!accs.length) acc.innerHTML = `<div class="muted">Ще немає акаунтів. Додай перший — і пристрої з'являться в Home Assistant.</div>`;
  for (const a of accs) {
    const st = (s.accounts[a.id] || {});
    const cls = STATE[st.state] || "pill--muted";
    const sub = st.error ? st.error : `регіон ${a.region} · пристроїв: ${st.devices ?? "—"}`;
    const row = document.createElement("div"); row.className = "row";
    row.innerHTML = `
      <div class="row__main">
        <div class="row__title">${a.email}</div>
        <div class="row__sub">${sub}</div>
      </div>
      <div class="row__right">
        <span class="pill ${cls}">${st.state || (a.enabled ? "—" : "disabled")}</span>
        <button class="btn btn--danger" data-del="${a.id}">Видалити</button>
      </div>`;
    acc.appendChild(row);
  }
  acc.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    if (!confirm("Видалити акаунт?")) return;
    await api("api/accounts/" + b.dataset.del, { method: "DELETE" });
    toast("Акаунт видалено"); refresh();
  });

  // plugins
  const pl = $("#plugins"); pl.innerHTML = "";
  for (const p of s.plugins) {
    const row = document.createElement("div"); row.className = "row";
    row.innerHTML = `
      <div class="row__main">
        <div class="row__title">${p.name}</div>
        <div class="row__sub">обробляє: ${p.handles.join(", ") || "—"}</div>
      </div>
      <label class="switch">
        <input type="checkbox" ${p.enabled ? "checked" : ""} data-plugin="${p.slug}">
        <span></span>
      </label>`;
    pl.appendChild(row);
  }
  pl.querySelectorAll("[data-plugin]").forEach(c => c.onchange = async () => {
    await api("api/plugins/" + c.dataset.plugin, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: c.checked }),
    });
    toast("Збережено"); refresh();
  });
}

// add-account form
$("#addBtn").onclick = () => $("#addForm").classList.toggle("hidden");
$("#cancelAdd").onclick = () => $("#addForm").classList.add("hidden");
$("#addForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await api("api/accounts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(f)),
    });
    e.target.reset(); $("#addForm").classList.add("hidden");
    toast("Акаунт додано — підключаюсь…"); refresh();
  } catch (err) { toast("Помилка: " + err.message); }
};

refresh();
setInterval(refresh, 5000);
