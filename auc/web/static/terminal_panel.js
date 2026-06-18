/** Code 模式底部终端（VS Code 风格多标签 + xterm ESM + WebSocket PTY） */

import { t } from "./i18n.js";

const $ = (sel) => document.querySelector(sel);

const XTERM_MOD = new URL("./vendor/xterm.esm.js?v=23", import.meta.url);
const FIT_MOD = new URL("./vendor/addon-fit.esm.js?v=23", import.meta.url);
const SHELL_LABEL = "bash";

/** @type {Map<number, TerminalSession>} */
const sessions = new Map();
let activeSessionId = null;
let sessionCounter = 0;
let xtermLibs = null;
let xtermLoading = null;
let hostResizeObserver = null;

/** @typedef {{
 *   id: number,
 *   title: string,
 *   term: import('@xterm/xterm').Terminal,
 *   fitAddon: import('@xterm/addon-fit').FitAddon | null,
 *   hostEl: HTMLElement,
 *   socket: WebSocket | null,
 *   pendingInput: string | null,
 *   reconnectNotice: boolean,
 * }} TerminalSession */

function monacoThemeName() {
  const id = document.getElementById("app")?.dataset?.colorTheme || "monokai";
  const dark = !["light-plus", "github-light"].includes(id);
  return dark ? "monokai" : "default";
}

function xtermTheme() {
  const dark = monacoThemeName() === "monokai";
  if (!dark) {
    return {
      background: "#ffffff",
      foreground: "#1a2332",
      cursor: "#3b82f6",
      selectionBackground: "#dbeafe",
    };
  }
  return {
    background: "#272822",
    foreground: "#f8f8f2",
    cursor: "#a6e22e",
    selectionBackground: "#49483e",
  };
}

async function loadXtermLibs() {
  if (xtermLibs) return xtermLibs;
  if (!xtermLoading) {
    xtermLoading = (async () => {
      const [xtermMod, fitMod] = await Promise.all([import(XTERM_MOD.href), import(FIT_MOD.href)]);
      const Terminal = xtermMod.Terminal || xtermMod.default?.Terminal;
      const FitAddon = fitMod.FitAddon || fitMod.default?.FitAddon;
      if (!Terminal) throw new Error("xterm ESM 缺少 Terminal 导出");
      xtermLibs = { Terminal, FitAddon };
      return xtermLibs;
    })();
  }
  return xtermLoading;
}

function showTerminalLoadError(message) {
  const hosts = $("#terminal-hosts");
  if (!hosts) return;
  hosts.innerHTML = `<div class="terminal-load-error">${message}</div>`;
}

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/api/terminal/ws`;
}

function nextSessionTitle() {
  const same = [...sessions.values()].filter((s) => s.title === SHELL_LABEL || s.title.startsWith(`${SHELL_LABEL} (`)).length;
  if (same === 0) return SHELL_LABEL;
  return `${SHELL_LABEL} (${same + 1})`;
}

function sendResize(session) {
  if (!session?.term || !session.socket || session.socket.readyState !== WebSocket.OPEN) return;
  try {
    session.fitAddon?.fit();
  } catch {
    /* layout not ready */
  }
  session.socket.send(
    JSON.stringify({
      type: "resize",
      cols: session.term.cols || 80,
      rows: session.term.rows || 24,
    }),
  );
}

function resizeActiveSession() {
  const session = activeSessionId != null ? sessions.get(activeSessionId) : null;
  if (session) sendResize(session);
}

function flushPendingInput(session) {
  if (!session.pendingInput || !session.socket || session.socket.readyState !== WebSocket.OPEN) return;
  session.socket.send(session.pendingInput);
  session.pendingInput = null;
}

function sendInput(session, data) {
  if (!session.socket || session.socket.readyState !== WebSocket.OPEN) {
    session.pendingInput = data;
    connectSession(session);
    return;
  }
  session.socket.send(data);
}

function connectSession(session) {
  if (session.socket && (session.socket.readyState === WebSocket.OPEN || session.socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  const socket = new WebSocket(wsUrl());
  session.socket = socket;
  socket.binaryType = "arraybuffer";
  socket.addEventListener("open", () => {
    session.reconnectNotice = false;
    if (session.id === activeSessionId) sendResize(session);
    flushPendingInput(session);
    if (session.id === activeSessionId) session.term.focus();
  });
  socket.addEventListener("message", (ev) => {
    if (ev.data instanceof ArrayBuffer) {
      session.term.write(new Uint8Array(ev.data));
    } else if (ev.data instanceof Blob) {
      ev.data.arrayBuffer().then((buf) => session.term.write(new Uint8Array(buf)));
    } else {
      session.term.write(String(ev.data));
    }
  });
  socket.addEventListener("close", () => {
    session.socket = null;
    if (session.id === activeSessionId && isTerminalOpen() && !session.reconnectNotice) {
      session.reconnectNotice = true;
      session.term.write(`\r\n\x1b[33m[${t("terminal.disconnected")}]\x1b[0m\r\n`);
    }
  });
  socket.addEventListener("error", () => {
    session.term.write(`\r\n\x1b[31m[${t("terminal.connectFail")}]\x1b[0m\r\n`);
  });
}

function disconnectSession(session) {
  session.pendingInput = null;
  session.reconnectNotice = false;
  if (session.socket) {
    session.socket.close();
    session.socket = null;
  }
}

function ensureHostObserver() {
  if (hostResizeObserver) return;
  const hosts = $("#terminal-hosts");
  if (!hosts) return;
  hostResizeObserver = new ResizeObserver(() => {
    if (isTerminalOpen()) resizeActiveSession();
  });
  hostResizeObserver.observe(hosts);
}

function createSessionHost(id) {
  const hosts = $("#terminal-hosts");
  const el = document.createElement("div");
  el.className = "terminal-host";
  el.dataset.sessionId = String(id);
  el.hidden = true;
  hosts.appendChild(el);
  return el;
}

async function createSession({ activate = true } = {}) {
  let libs;
  try {
    libs = await loadXtermLibs();
  } catch (err) {
    showTerminalLoadError(t("terminal.loadFail", { msg: err?.message || err }));
    return null;
  }

  $("#terminal-hosts")?.querySelector(".terminal-load-error")?.remove();

  const id = ++sessionCounter;
  const hostEl = createSessionHost(id);
  const { Terminal, FitAddon } = libs;
  const term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: '"JetBrains Mono", "Fira Code", Menlo, Consolas, monospace',
    theme: xtermTheme(),
    allowProposedApi: true,
  });
  let fitAddon = null;
  if (FitAddon) {
    fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
  }
  term.open(hostEl);

  /** @type {TerminalSession} */
  const session = {
    id,
    title: nextSessionTitle(),
    term,
    fitAddon,
    hostEl,
    socket: null,
    pendingInput: null,
    reconnectNotice: false,
  };

  term.onData((data) => sendInput(session, data));
  term.onResize(() => {
    if (session.id === activeSessionId) sendResize(session);
  });

  sessions.set(id, session);
  connectSession(session);
  ensureHostObserver();

  if (activate) activateSession(id);
  else renderTabs();
  return session;
}

function activateSession(id) {
  const session = sessions.get(id);
  if (!session) return;
  activeSessionId = id;
  for (const s of sessions.values()) {
    s.hostEl.hidden = s.id !== id;
  }
  renderTabs();
  hidePickerMenu();
  requestAnimationFrame(() => {
    sendResize(session);
    session.term.focus();
  });
}

function closeSession(id) {
  const session = sessions.get(id);
  if (!session) return;
  disconnectSession(session);
  session.term.dispose();
  session.hostEl.remove();
  sessions.delete(id);

  if (sessions.size === 0) {
    activeSessionId = null;
    renderTabs();
    hidePickerMenu();
    return;
  }
  if (activeSessionId === id) {
    const ids = [...sessions.keys()];
    activateSession(ids[ids.length - 1]);
  } else {
    renderTabs();
    renderPickerMenu();
  }
}

function renderTabs() {
  const bar = $("#terminal-tabs");
  if (!bar) return;
  bar.innerHTML = "";
  for (const session of sessions.values()) {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "terminal-tab" + (session.id === activeSessionId ? " active" : "");
    tab.title = session.title;
    tab.innerHTML =
      `<span class="terminal-tab-label">${session.title}</span>` +
      `<span class="terminal-tab-close" aria-label="${t("terminal.close")}" title="${t("terminal.close")}">×</span>`;
    tab.addEventListener("click", (ev) => {
      if (ev.target.closest(".terminal-tab-close")) return;
      activateSession(session.id);
    });
    tab.querySelector(".terminal-tab-close")?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      closeSession(session.id);
    });
    bar.appendChild(tab);
  }
}

function hidePickerMenu() {
  $("#terminal-picker-menu")?.classList.add("hidden");
  $("#terminal-picker")?.setAttribute("aria-expanded", "false");
}

function togglePickerMenu() {
  const menu = $("#terminal-picker-menu");
  const btn = $("#terminal-picker");
  if (!menu || !btn || sessions.size === 0) return;
  const open = menu.classList.toggle("hidden");
  if (!open) {
    renderPickerMenu();
    btn.setAttribute("aria-expanded", "true");
  } else {
    btn.setAttribute("aria-expanded", "false");
  }
}

function renderPickerMenu() {
  const menu = $("#terminal-picker-menu");
  if (!menu) return;
  menu.innerHTML = "";
  for (const session of sessions.values()) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "terminal-picker-item" + (session.id === activeSessionId ? " active" : "");
    item.textContent = session.title;
    item.addEventListener("click", () => {
      activateSession(session.id);
      hidePickerMenu();
    });
    menu.appendChild(item);
  }
}

export function isTerminalOpen() {
  return $("#terminal-panel")?.classList.contains("is-open");
}

export function getTerminalHeight() {
  const panel = $("#terminal-panel");
  if (!panel) return 240;
  return parseInt(panel.style.getPropertyValue("--terminal-height") || "240", 10) || 240;
}

export function setTerminalHeight(px) {
  const h = Math.max(120, Math.min(px, window.innerHeight * 0.65));
  const panel = $("#terminal-panel");
  if (panel) panel.style.setProperty("--terminal-height", `${h}px`);
  localStorage.setItem("auc-terminal-height", String(h));
  resizeActiveSession();
  window.dispatchEvent(new Event("auc-terminal-resize"));
  return h;
}

export async function openTerminal() {
  const panel = $("#terminal-panel");
  const btn = $("#btn-terminal");
  if (!panel) return;
  panel.classList.add("is-open");
  panel.classList.remove("is-collapsed");
  btn?.classList.add("active");
  localStorage.setItem("auc-terminal-open", "1");

  if (sessions.size === 0) {
    await createSession({ activate: true });
    return;
  }
  if (activeSessionId != null && sessions.has(activeSessionId)) {
    activateSession(activeSessionId);
  } else {
    activateSession([...sessions.keys()][0]);
  }
}

export function closeTerminal() {
  const panel = $("#terminal-panel");
  const btn = $("#btn-terminal");
  panel?.classList.remove("is-open");
  panel?.classList.add("is-collapsed");
  btn?.classList.remove("active");
  localStorage.setItem("auc-terminal-open", "0");
  hidePickerMenu();
  window.dispatchEvent(new Event("auc-terminal-resize"));
}

export function toggleTerminal() {
  if (isTerminalOpen()) closeTerminal();
  else void openTerminal();
}

export async function newTerminal() {
  if (!isTerminalOpen()) await openTerminal();
  await createSession({ activate: true });
}

export function refreshTerminalTheme() {
  for (const session of sessions.values()) {
    session.term.options.theme = xtermTheme();
  }
}

export function initTerminalPanel() {
  const panel = $("#terminal-panel");
  if (!panel) return;

  const savedH = parseInt(localStorage.getItem("auc-terminal-height") || "240", 10);
  panel.style.setProperty("--terminal-height", `${savedH}px`);

  $("#btn-terminal")?.addEventListener("click", () => toggleTerminal());
  $("#terminal-close")?.addEventListener("click", () => closeTerminal());
  $("#terminal-new")?.addEventListener("click", () => void newTerminal());
  $("#terminal-picker")?.addEventListener("click", (ev) => {
    ev.stopPropagation();
    togglePickerMenu();
  });

  document.addEventListener("click", (ev) => {
    if (!ev.target.closest(".terminal-picker-wrap")) hidePickerMenu();
  });

  const handle = $("#terminal-resize-handle");
  if (handle) {
    let startY = 0;
    let startH = 0;
    handle.addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      startY = ev.clientY;
      startH = getTerminalHeight();
      const onMove = (e) => {
        setTerminalHeight(startH - (e.clientY - startY));
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  window.addEventListener("keydown", (ev) => {
    if (ev.ctrlKey && ev.shiftKey && ev.code === "Backquote") {
      ev.preventDefault();
      void newTerminal();
    }
  });

  window.addEventListener("resize", () => {
    if (isTerminalOpen()) resizeActiveSession();
  });

  if (localStorage.getItem("auc-terminal-open") === "1") {
    void openTerminal();
  } else {
    panel.classList.add("is-collapsed");
  }

  window.addEventListener("auc-locale-change", () => renderTabs());
}
