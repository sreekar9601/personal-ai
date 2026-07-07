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
  switchView("money");
}

function switchView(name) {
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  $("view-" + name).classList.remove("hidden");
  document.querySelectorAll("#tabbar .tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === name)
  );
  $("chat-inputbar").classList.toggle("hidden", name !== "chat");
  if (name === "status") { loadStatus(); refreshPushUI(); }
  if (name === "money") loadMoney();
  if (name === "notes" && !$("notes-body").dataset.loaded) browseNotes("vault");
}

/* ---------- Chat tab ---------- */
function bubble(cls, html) {
  $("chat-empty")?.remove();
  const div = document.createElement("div");
  div.className = "bubble " + cls;
  div.innerHTML = html;
  $("chat-log").appendChild(div);
  div.scrollIntoView({ block: "end" });
  return div;
}

function approvalCard(ev) {
  const div = bubble("assistant approval-card",
    `<div class="approval-head">🔐 Approval needed</div>` +
    ev.items.map((s) => `<pre class="approval-item">${esc(s)}</pre>`).join("") +
    `<div class="approval-actions">
       <button class="ok primary">Approve</button>
       <button class="no">Deny</button>
     </div>`);
  const done = (label) => {
    div.querySelector(".approval-actions").innerHTML =
      `<span class="muted">${label}</span>`;
  };
  div.querySelector(".ok").addEventListener("click", async () => {
    done("✅ Approved — running…");
    try { handleChatEvent(await api(`/api/approvals/${ev.token}`, { approve: true })); }
    catch (e) { bubble("assistant error-bubble", esc(e.message)); }
  });
  div.querySelector(".no").addEventListener("click", async () => {
    done("❌ Denied");
    try { handleChatEvent(await api(`/api/approvals/${ev.token}`, { approve: false })); }
    catch (e) { bubble("assistant error-bubble", esc(e.message)); }
  });
}

let typingEl = null;
function handleChatEvent(ev) {
  if (ev.type === "typing") {
    if (!typingEl) typingEl = bubble("assistant typing", "<span></span><span></span><span></span>");
    return;
  }
  if (typingEl) { typingEl.remove(); typingEl = null; }
  if (ev.type === "reply") bubble("assistant", esc(ev.text).replace(/\n/g, "<br>"));
  else if (ev.type === "approval") approvalCard(ev);
  else if (ev.type === "error") bubble("assistant error-bubble", esc(ev.text));
}

async function sendChat() {
  const input = $("chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  bubble("user", esc(text).replace(/\n/g, "<br>"));
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      credentials: "same-origin",
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (line) handleChatEvent(JSON.parse(line.slice(6)));
      }
    }
    if (typingEl) { typingEl.remove(); typingEl = null; }
  } catch (e) {
    if (typingEl) { typingEl.remove(); typingEl = null; }
    bubble("assistant error-bubble", esc(e.message || String(e)));
  }
}

/* ---------- Money tab ---------- */
const moneyState = { month: new Date() };

function monthKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function shiftMonth(delta) {
  moneyState.month.setMonth(moneyState.month.getMonth() + delta);
  loadMoney();
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function money(n) {
  const v = Math.abs(Number(n) || 0);
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

async function loadMoney() {
  const key = monthKey(moneyState.month);
  $("month-label").textContent = moneyState.month.toLocaleDateString(undefined,
    { month: "long", year: "numeric" });
  const el = $("money-body");
  try {
    const [summary, ledger] = await Promise.all([
      api(`/api/finance/summary?month=${key}`),
      api(`/api/finance/ledger?month=${key}&limit=30`),
    ]);
    const t = summary.totals || {};
    const spent = Math.abs(t.spent || 0);
    const income = t.income || 0;
    let html = `<div class="cards">` +
      card("Spent", money(spent)) +
      card("Income", money(income)) +
      `</div>`;

    const cats = (summary.by_category || []).filter((c) => (c.net || 0) < 0);
    if (cats.length) {
      const max = Math.max(...cats.map((c) => Math.abs(c.net)));
      // Widths are applied via CSSOM below — CSP (style-src 'self') strips
      // inline style attributes, but scripted style assignment is allowed.
      html += `<h2>By category</h2><div class="list">` + cats.map((c) => `
        <div class="row">
          <div class="row-main">
            <span>${esc(c.category)}</span>
            <span class="row-amount">${money(c.net)}</span>
          </div>
          <div class="bar"><div class="bar-fill" data-w="${Math.round(100 * Math.abs(c.net) / max)}"></div></div>
        </div>`).join("") + `</div>`;
    }

    const rows = ledger.rows || [];
    if (rows.length) {
      html += `<h2>Transactions</h2><div class="list">` + rows.map((r) => `
        <div class="row">
          <div class="row-main">
            <span class="row-desc">${esc(r.description || "—")}</span>
            <span class="row-amount ${Number(r.amount) > 0 ? "pos" : ""}">${money(r.amount)}</span>
          </div>
          <div class="row-sub">${esc(r.date || "")} · ${esc(r.category || "")}</div>
        </div>`).join("") + `</div>`;
    }
    if (!cats.length && !rows.length) {
      html += `<div class="placeholder small">No transactions for ${esc(key)}.<br>
        <span class="muted">Log expenses via Telegram or drop a CSV in finance/imports/.</span></div>`;
    }
    el.innerHTML = html;
    el.querySelectorAll(".bar-fill").forEach((b) => { b.style.width = b.dataset.w + "%"; });
  } catch (e) {
    if (String(e.message).includes("Not signed in")) return boot();
    el.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

/* ---------- Notes tab ---------- */
function mdToHtml(md) {
  let h = esc(md);
  h = h.replace(/\[\[([^\]]+)\]\]/g, '<span class="wikilink">$1</span>');
  h = h.replace(/^###### (.*)$/gm, "<h6>$1</h6>")
       .replace(/^##### (.*)$/gm, "<h5>$1</h5>")
       .replace(/^#### (.*)$/gm, "<h4>$1</h4>")
       .replace(/^### (.*)$/gm, "<h3>$1</h3>")
       .replace(/^## (.*)$/gm, "<h2>$1</h2>")
       .replace(/^# (.*)$/gm, "<h1>$1</h1>");
  h = h.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/^[-*] (.*)$/gm, "<li>$1</li>");
  h = h.replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`);
  h = h.replace(/\n{2,}/g, "</p><p>");
  return `<div class="note-md"><p>${h}</p></div>`;
}

async function browseNotes(path) {
  const el = $("notes-body");
  el.dataset.loaded = "1";
  try {
    const res = await api(`/api/notes?path=${encodeURIComponent(path)}`);
    if (res.type === "dir") {
      const up = path !== "vault"
        ? `<div class="row nav-row" data-path="${esc(path.split("/").slice(0, -1).join("/"))}">← up</div>` : "";
      el.innerHTML = up + (res.entries.length ? res.entries.map((e2) => `
        <div class="row nav-row" data-path="${esc(path + "/" + e2.name)}">
          ${e2.dir ? "📁" : "📄"} ${esc(e2.name)}
        </div>`).join("") : `<div class="placeholder small">Empty.</div>`);
    } else {
      el.innerHTML = `<div class="row nav-row" data-path="${esc(res.path.split("/").slice(0, -1).join("/"))}">← back</div>
        <h2 class="note-title">${esc(res.path.split("/").pop())}</h2>` + mdToHtml(res.content);
    }
    el.querySelectorAll(".nav-row").forEach((r) =>
      r.addEventListener("click", () => browseNotes(r.dataset.path)));
  } catch (e) {
    if (String(e.message).includes("Not signed in")) return boot();
    el.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
}

let searchTimer = null;
async function searchNotes(q) {
  if (!q.trim()) return browseNotes("vault");
  const el = $("notes-body");
  try {
    const res = await api(`/api/notes/search?q=${encodeURIComponent(q)}`);
    el.innerHTML = res.hits.length ? res.hits.map((h) => `
      <div class="row nav-row" data-path="${esc(h.path)}">
        <div class="row-main"><span>📄 ${esc(h.title)}</span></div>
        <div class="row-sub">${esc(h.snippet).replace(/«/g, "<strong>").replace(/»/g, "</strong>")}</div>
      </div>`).join("") : `<div class="placeholder small">No matches.</div>`;
    el.querySelectorAll(".nav-row").forEach((r) =>
      r.addEventListener("click", () => browseNotes(r.dataset.path)));
  } catch (e) {
    el.innerHTML = `<div class="error">${esc(e.message)}</div>`;
  }
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

/* ---------- Photo capture ---------- */
async function downscaleImage(file, maxDim = 1600, quality = 0.85) {
  // Keep uploads (and vision tokens) small; iOS camera photos are huge.
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, maxDim / Math.max(bmp.width, bmp.height));
    if (scale === 1 && file.size < 2 * 1024 * 1024) return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((ok) => canvas.toBlob(ok, "image/jpeg", quality));
    return blob || file;
  } catch (_) {
    return file; // downscale is an optimisation, never a blocker
  }
}

async function sendPhoto(file) {
  if (!file) return;
  switchView("chat");
  const url = URL.createObjectURL(file);
  bubble("user", `<img class="photo-thumb" src="${url}" alt="photo">`);
  handleChatEvent({ type: "typing" });
  try {
    const blob = await downscaleImage(file);
    const form = new FormData();
    form.append("file", blob, "photo.jpg");
    const res = await fetch("/api/capture/photo", {
      method: "POST", body: form, credentials: "same-origin",
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    handleChatEvent(await res.json());
  } catch (e) {
    handleChatEvent({ type: "error", text: e.message || String(e) });
  }
}

/* ---------- Web Push ---------- */
async function refreshPushUI() {
  const btn = $("btn-push");
  const note = $("push-note");
  btn.classList.add("hidden");
  note.classList.add("hidden");
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    const standalone = window.navigator.standalone === true ||
      window.matchMedia("(display-mode: standalone)").matches;
    if (!standalone) {
      note.textContent = "Install the app (Share → Add to Home Screen) to enable notifications.";
      note.classList.remove("hidden");
    }
    return;
  }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) {
    note.textContent = "🔔 Notifications are on (briefings, reflections).";
    note.classList.remove("hidden");
  } else {
    btn.classList.remove("hidden");
  }
}

async function enablePush() {
  try {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") throw new Error("Notifications were not allowed.");
    const { key } = await api("/api/push/key");
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: new Uint8Array(b64uToBuf(key)),
    });
    await api("/api/push/subscribe", { subscription: sub.toJSON() });
    await refreshPushUI();
  } catch (e) {
    const note = $("push-note");
    note.textContent = e.message || String(e);
    note.classList.remove("hidden");
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
  $("btn-push").addEventListener("click", enablePush);
  $("btn-logout").addEventListener("click", async () => {
    await api("/api/logout", {});
    location.reload();
  });
  document.querySelectorAll("#tabbar .tab").forEach((t) =>
    t.addEventListener("click", () => switchView(t.dataset.view))
  );
  $("month-prev").addEventListener("click", () => shiftMonth(-1));
  $("month-next").addEventListener("click", () => shiftMonth(1));
  $("chat-send").addEventListener("click", sendChat);
  $("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); sendChat(); }
  });
  $("chat-photo").addEventListener("click", () => $("photo-file").click());
  $("photo-file").addEventListener("change", (e) => {
    sendPhoto(e.target.files[0]);
    e.target.value = "";
  });
  $("notes-search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => searchNotes(e.target.value), 250);
  });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
  boot().catch((e) => showError(e.message || String(e)));
});
