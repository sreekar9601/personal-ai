/* Personal AI — PWA shell (slice P1: auth + status; tabs fill in P2/P3). */
"use strict";

const $ = (id) => document.getElementById(id);

/* ---------- base64url <-> ArrayBuffer (WebAuthn wire format) ---------- */
function b64uToBuf(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  const pad = s.length % 4 ? "====".slice(s.length % 4) : "";
  const bin = atob(s + pad);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}
function bufToB64u(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/* ---------- API helper ---------- */
async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

/* ---------- Auth flows ---------- */
function showError(msg) {
  const el = $("auth-error");
  el.textContent = msg;
  el.classList.remove("hidden");
}
function authScreen(which) {
  $("screen-auth").classList.remove("hidden");
  $("screen-app").classList.add("hidden");
  $("tabbar").classList.add("hidden");
  for (const id of ["auth-login", "auth-enroll", "auth-recover", "recovery-show"])
    $(id).classList.toggle("hidden", id !== which);
  $("auth-error").classList.add("hidden");
}

async function doEnroll(tokenOverride) {
  const token = tokenOverride || $("enroll-token").value.trim();
  if (!token) return showError("Paste the enrollment token from the server log.");
  try {
    const res = await fetch("/api/webauthn/register/options", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const opts = (await res.json());
    const pk = opts.publicKey || opts;
    pk.challenge = b64uToBuf(pk.challenge);
    pk.user.id = b64uToBuf(pk.user.id);
    (pk.excludeCredentials || []).forEach((c) => (c.id = b64uToBuf(c.id)));
    const cred = await navigator.credentials.create({ publicKey: pk });
    const payload = {
      id: cred.id,
      rawId: bufToB64u(cred.rawId),
      type: cred.type,
      clientExtensionResults: cred.getClientExtensionResults(),
      response: {
        clientDataJSON: bufToB64u(cred.response.clientDataJSON),
        attestationObject: bufToB64u(cred.response.attestationObject),
      },
    };
    const out = await api("/api/webauthn/register/verify", { token, credential: payload });
    $("recovery-code-text").textContent = out.recovery_code;
    authScreen("recovery-show");
  } catch (e) {
    showError(e.message || String(e));
  }
}

async function doLogin() {
  try {
    const res = await fetch("/api/webauthn/login/options", { method: "POST" });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const opts = await res.json();
    const pk = opts.publicKey || opts;
    pk.challenge = b64uToBuf(pk.challenge);
    (pk.allowCredentials || []).forEach((c) => (c.id = b64uToBuf(c.id)));
    const cred = await navigator.credentials.get({ publicKey: pk });
    const payload = {
      id: cred.id,
      rawId: bufToB64u(cred.rawId),
      type: cred.type,
      clientExtensionResults: cred.getClientExtensionResults(),
      response: {
        clientDataJSON: bufToB64u(cred.response.clientDataJSON),
        authenticatorData: bufToB64u(cred.response.authenticatorData),
        signature: bufToB64u(cred.response.signature),
        userHandle: cred.response.userHandle ? bufToB64u(cred.response.userHandle) : null,
      },
    };
    await api("/api/webauthn/login/verify", { credential: payload });
    enterApp();
  } catch (e) {
    showError(e.message || String(e));
  }
}

async function doRecover() {
  try {
    const out = await api("/api/webauthn/recover", { code: $("recover-code").value.trim() });
    authScreen("auth-enroll");
    $("enroll-token").value = out.enroll_token;
  } catch (e) {
    showError(e.message || String(e));
  }
}

/* ---------- App ---------- */
function enterApp() {
  $("screen-auth").classList.add("hidden");
  $("screen-app").classList.remove("hidden");
  $("tabbar").classList.remove("hidden");
  switchView("status"); // P1: status is the live tab
  loadStatus();
}

function switchView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  $("view-" + name).classList.remove("hidden");
  document.querySelectorAll("#tabbar .tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === name)
  );
  if (name === "status") loadStatus();
}

function card(title, value, sub) {
  return `<div class="card"><div class="card-title">${title}</div>
    <div class="card-value">${value}</div>
    ${sub ? `<div class="card-sub">${sub}</div>` : ""}</div>`;
}

async function loadStatus() {
  const el = $("status-body");
  try {
    const s = await api("/api/status");
    const up = `${Math.floor(s.uptime_s / 3600)}h${String(Math.floor(s.uptime_s / 60) % 60).padStart(2, "0")}m`;
    const budget = s.budget_usd > 0
      ? `$${s.spend_today_usd.toFixed(2)} / $${s.budget_usd.toFixed(2)}`
      : `$${s.spend_today_usd.toFixed(2)}`;
    el.innerHTML =
      card("Uptime", up, s.deployed ? "deployed" : "local") +
      card("Spend today", budget,
        `${s.tokens_in.toLocaleString()} in · ${s.tokens_out.toLocaleString()} out`) +
      card("Inbox", `${s.inbox_count}`, "captures waiting") +
      card("Last sync", s.last_commit ? s.last_commit.split(" (")[0] : "—",
        s.last_commit && s.last_commit.includes("(") ? s.last_commit.split("(")[1].replace(")", "") : "") +
      card("Models", s.models.default.split(":").pop(),
        `strong: ${s.models.strong.split(":").pop()}`) +
      (s.kill_switch ? card("Kill switch", "ON", "writes disabled") : "");
  } catch (e) {
    if (String(e.message).includes("Not signed in")) return boot();
    el.innerHTML = `<div class="error">${e.message}</div>`;
  }
}

/* ---------- Boot ---------- */
async function boot() {
  // iOS install nudge: outside standalone mode, push + the best UX are unavailable.
  const standalone = window.navigator.standalone === true ||
    window.matchMedia("(display-mode: standalone)").matches;
  $("install-banner").classList.toggle("hidden", standalone);

  const me = await api("/api/me");
  const params = new URLSearchParams(location.search);
  const enrollToken = params.get("enroll");
  if (me.authenticated) return enterApp();
  if (!me.enrolled) {
    authScreen("auth-enroll");
    if (enrollToken) $("enroll-token").value = enrollToken;
  } else {
    authScreen("auth-login");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("btn-enroll").addEventListener("click", () => doEnroll());
  $("btn-login").addEventListener("click", doLogin);
  $("btn-show-recover").addEventListener("click", () => authScreen("auth-recover"));
  $("btn-back-login").addEventListener("click", () => authScreen("auth-login"));
  $("btn-recover").addEventListener("click", doRecover);
  $("btn-recovery-done").addEventListener("click", enterApp);
  $("btn-logout").addEventListener("click", async () => {
    await api("/api/logout", {});
    location.reload();
  });
  document.querySelectorAll("#tabbar .tab").forEach((t) =>
    t.addEventListener("click", () => switchView(t.dataset.view))
  );
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
  boot().catch((e) => showError(e.message || String(e)));
});
