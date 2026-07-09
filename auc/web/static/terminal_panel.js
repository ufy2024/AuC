/** Code 模式底部终端（VS Code 风格多标签 + xterm ESM + WebSocket PTY） */

import { t } from "./i18n.js";

const $ = (sel) => document.querySelector(sel);

const XTERM_MOD = new URL("./vendor/xterm.esm.js?v=23", import.meta.url);
const FIT_MOD = new URL("./vendor/addon-fit.esm.js?v=23", import.meta.url);
const SHELL_LABEL = "bash";
const OUTPUT_BUFFER_MAX = 48_000;
const AUTO_AGENT_KEY = "auc-terminal-auto-agent";

/** @type {Map<number, TerminalSession>} */
const sessions = new Map();
let activeSessionId = null;
let sessionCounter = 0;
let xtermLibs = null;
let xtermLoading = null;
let hostResizeObserver = null;

/** @type {{ text: string, kind: "error" | "selection", sessionId: number } | null} */
let actionBarPayload = null;
let actionBarHideTimer = null;

const ERROR_MARKERS = [
  /Traceback \(most recent call last\)/,
  /SyntaxError:/,
  /TypeError:/,
  /NameError:/,
  /ValueError:/,
  /ModuleNotFoundError:/,
  /ImportError:/,
  /FileNotFoundError:/,
  /PermissionError:/,
  /RuntimeError:/,
  /AssertionError:/,
  /CommandNotFoundError:/,
  /\bError:\s/,
  /\bERROR\b/,
  /npm ERR!/,
  /\bERR!/,
  /command not found/i,
  /Permission denied/i,
  /No such file or directory/i,
  /\bfatal:/i,
  /\bpanic:/i,
  /FAILED\b/,
  /✖/,
  /Exit code [1-9]\d*/i,
];

/** @typedef {{
 *   id: number,
 *   title: string,
 *   term: import('@xterm/xterm').Terminal,
 *   fitAddon: import('@xterm/addon-fit').FitAddon | null,
 *   hostEl: HTMLElement,
 *   socket: WebSocket | null,
 *   pendingInput: string | null,
 *   reconnectNotice: boolean,
 *   reconnectAttempts: number,
 *   reconnectTimer: number | null,
 *   heartbeatTimer: number | null,
 *   manualClose: boolean,
 *   outputBuffer: string,
 *   lastErrorText: string | null,
 * }} TerminalSession */

/** 终端内可点击跳转的 URL（http/https 及 localhost:port） */
const TERMINAL_URL_RE =
  /(?:https?:\/\/[^\s<>"'`[\]{}|\\^]+|(?:localhost|127\.0\.0\.1):\d{2,5}(?:\/[^\s]*)?)/gi;

function trimTerminalUrl(raw) {
  let url = String(raw || "").trim();
  while (/[.,;:!?)}\]'"]+$/.test(url)) url = url.slice(0, -1);
  return url;
}

function normalizeTerminalHref(raw) {
  const url = trimTerminalUrl(raw);
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  if (/^(?:localhost|127\.0\.0\.1):\d+/i.test(url)) return `http://${url}`;
  return url;
}

function openTerminalLink(href) {
  const url = normalizeTerminalHref(href);
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

/**
 * 构造「字符串下标 → 终端单元列(1-based)」映射。
 * 终端里中文/符号是双宽字符（占 2 列但 translateToString 只产出 1 个 JS 字符），
 * 若直接用 match.index 当列号，链接下划线会相对真实文本偏移。这里按每个单元的
 * 宽度累计列号，使下划线与 URL 文本严格对齐。
 */
function buildColumnMap(line) {
  const map = [];
  const cols = line.length || 0;
  for (let x = 0; x < cols; x++) {
    const cell = line.getCell(x);
    if (!cell) continue;
    if (cell.getWidth() === 0) continue; // 双宽字符的尾随空单元，不产出字符
    let chars = cell.getChars();
    if (chars === "") chars = " ";
    for (let k = 0; k < chars.length; k++) map.push(x + 1);
  }
  return map;
}

function attachTerminalLinks(term) {
  if (typeof term.registerLinkProvider !== "function") return;
  term.registerLinkProvider({
    provideLinks(lineNumber, callback) {
      const line = term.buffer.active.getLine(lineNumber - 1);
      if (!line) {
        callback(undefined);
        return;
      }
      const text = line.translateToString(false);
      // 优先用单元宽度映射列号；旧版 xterm 无 getCell 时回退到字符下标。
      const colMap =
        typeof line.getCell === "function" ? buildColumnMap(line) : null;
      const links = [];
      TERMINAL_URL_RE.lastIndex = 0;
      let match;
      while ((match = TERMINAL_URL_RE.exec(text)) !== null) {
        const raw = match[0];
        const href = normalizeTerminalHref(raw);
        if (!href) continue;
        const startIdx = match.index;
        const endIdx = match.index + raw.length - 1;
        const startX = colMap ? colMap[startIdx] ?? startIdx + 1 : startIdx + 1;
        const endX = colMap ? colMap[endIdx] ?? endIdx + 1 : endIdx + 1;
        links.push({
          text: raw,
          range: {
            start: { x: startX, y: lineNumber },
            end: { x: endX, y: lineNumber },
          },
          activate: (_event, linkText) => openTerminalLink(linkText || raw),
        });
      }
      callback(links.length ? links : undefined);
    },
  });
}

function stripAnsi(raw) {
  return String(raw || "")
    .replace(/\x1b\][^\x07]*(?:\x07|\x1b\\)/g, "")
    .replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, "")
    .replace(/\r/g, "");
}

function appendOutputBuffer(session, chunk) {
  const plain = stripAnsi(chunk);
  if (!plain) return;
  session.outputBuffer = (session.outputBuffer + plain).slice(-OUTPUT_BUFFER_MAX);
  const err = extractErrorBlock(session.outputBuffer);
  if (!err || err === session.lastErrorText) return;
  session.lastErrorText = err;
  showActionBar(err, "error", session.id);
  if (isAutoAgentEnabled()) {
    sendTextToAgent(err, { kind: "error", auto: true });
    hideActionBarSoon(4000);
  }
}

function extractErrorBlock(buffer) {
  const lines = buffer.split("\n");
  let start = -1;
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const line = lines[i];
    if (ERROR_MARKERS.some((re) => re.test(line))) {
      start = i;
      break;
    }
  }
  if (start < 0) return null;
  // 向上包含若干上下文行（命令或空行）
  const from = Math.max(0, start - 2);
  const block = lines.slice(from).join("\n").trim();
  return block.length >= 8 ? block : null;
}

function isAutoAgentEnabled() {
  return localStorage.getItem(AUTO_AGENT_KEY) !== "0";
}

function showActionBar(text, kind, sessionId) {
  actionBarPayload = { text: String(text || "").trim(), kind, sessionId };
  if (!actionBarPayload.text) return;
  const bar = $("#terminal-action-bar");
  const hint = $("#terminal-action-hint");
  if (!bar || !hint) return;
  hint.textContent =
    kind === "error" ? t("terminal.errorDetected") : t("terminal.selection");
  bar.classList.remove("hidden");
  if (actionBarHideTimer) clearTimeout(actionBarHideTimer);
  if (kind === "selection") {
    actionBarHideTimer = setTimeout(hideActionBar, 12_000);
  }
}

function hideActionBar() {
  $("#terminal-action-bar")?.classList.add("hidden");
  actionBarPayload = null;
  if (actionBarHideTimer) {
    clearTimeout(actionBarHideTimer);
    actionBarHideTimer = null;
  }
}

function hideActionBarSoon(ms = 3000) {
  if (actionBarHideTimer) clearTimeout(actionBarHideTimer);
  actionBarHideTimer = setTimeout(hideActionBar, ms);
}

export function sendTextToAgent(text, meta = {}) {
  const payload = String(text || "").trim();
  if (!payload) return;
  window.dispatchEvent(
    new CustomEvent("auc-terminal-to-agent", {
      detail: { text: payload, ...meta },
    }),
  );
}

async function copyActionText() {
  const text = actionBarPayload?.text;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  flashActionHint(t("terminal.copied"));
}

function sendActionToAgent() {
  const text = actionBarPayload?.text;
  if (!text) return;
  sendTextToAgent(text, { kind: actionBarPayload?.kind || "selection" });
  flashActionHint(t("terminal.sentAgent"));
  hideActionBarSoon(1500);
}

function flashActionHint(msg) {
  const hint = $("#terminal-action-hint");
  if (!hint) return;
  const prev = hint.textContent;
  hint.textContent = msg;
  setTimeout(() => {
    if (actionBarPayload && hint.textContent === msg) {
      hint.textContent =
        actionBarPayload.kind === "error"
          ? t("terminal.errorDetected")
          : t("terminal.selection");
    } else if (!actionBarPayload) {
      hint.textContent = prev;
    }
  }, 1600);
}

function bindSelectionActions(session) {
  const onSel = () => {
    if (session.id !== activeSessionId) return;
    const sel = session.term.getSelection()?.trim();
    if (sel) {
      showActionBar(sel, "selection", session.id);
    } else if (actionBarPayload?.kind === "selection") {
      hideActionBar();
    }
  };
  if (typeof session.term.onSelectionChange === "function") {
    session.term.onSelectionChange(onSel);
  }
  session.hostEl.addEventListener("mouseup", () => {
    requestAnimationFrame(onSel);
  });
}

function bindTerminalActionBar() {
  $("#terminal-action-copy")?.addEventListener("click", () => void copyActionText());
  $("#terminal-action-agent")?.addEventListener("click", () => sendActionToAgent());
  $("#terminal-action-dismiss")?.addEventListener("click", () => hideActionBar());
  const auto = $("#terminal-auto-agent");
  if (auto) {
    auto.checked = isAutoAgentEnabled();
    auto.addEventListener("change", () => {
      localStorage.setItem(AUTO_AGENT_KEY, auto.checked ? "1" : "0");
    });
  }
}

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
  hosts.querySelectorAll(".terminal-host, .terminal-load-error").forEach((el) => el.remove());
  const div = document.createElement("div");
  div.className = "terminal-load-error";
  div.textContent = message;
  const bar = $("#terminal-action-bar");
  if (bar) hosts.insertBefore(div, bar);
  else hosts.appendChild(div);
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
    // 用户主动输入 → 重置退避，立即尝试重连
    clearReconnectTimer(session);
    session.reconnectAttempts = 0;
    connectSession(session);
    return;
  }
  session.socket.send(data);
}

const MAX_RECONNECT_ATTEMPTS = 6;
const HEARTBEAT_INTERVAL_MS = 25_000;

function isControlMessage(data) {
  if (typeof data !== "string") return false;
  try {
    const payload = JSON.parse(data);
    return payload?.type === "ping" || payload?.type === "pong";
  } catch {
    return false;
  }
}

function startHeartbeat(session) {
  stopHeartbeat(session);
  session.heartbeatTimer = setInterval(() => {
    if (session.socket?.readyState === WebSocket.OPEN) {
      session.socket.send(JSON.stringify({ type: "ping" }));
    }
  }, HEARTBEAT_INTERVAL_MS);
}

function stopHeartbeat(session) {
  if (session.heartbeatTimer != null) {
    clearInterval(session.heartbeatTimer);
    session.heartbeatTimer = null;
  }
}

function clearReconnectTimer(session) {
  if (session.reconnectTimer != null) {
    clearTimeout(session.reconnectTimer);
    session.reconnectTimer = null;
  }
}

function scheduleReconnect(session) {
  if (session.manualClose) return;
  if (session.reconnectTimer != null) return;
  // 面板收起时不在后台重连，等下次打开/激活再连
  if (!isTerminalOpen()) return;
  if (session.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    if (session.id === activeSessionId && !session.reconnectNotice) {
      session.reconnectNotice = true;
      session.term.write(`\r\n\x1b[33m[${t("terminal.disconnected")}]\x1b[0m\r\n`);
    }
    return;
  }
  const attempt = session.reconnectAttempts++;
  if (attempt === 0 && session.id === activeSessionId) {
    session.term.write(`\r\n\x1b[2m[${t("terminal.reconnecting")}]\x1b[0m\r\n`);
  }
  const delay = Math.min(8000, 400 * 2 ** attempt) + Math.floor(Math.random() * 200);
  session.reconnectTimer = setTimeout(() => {
    session.reconnectTimer = null;
    connectSession(session);
  }, delay);
}

function connectSession(session) {
  if (session.socket && (session.socket.readyState === WebSocket.OPEN || session.socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  session.manualClose = false;
  clearReconnectTimer(session);
  const socket = new WebSocket(wsUrl());
  session.socket = socket;
  socket.binaryType = "arraybuffer";
  socket.addEventListener("open", () => {
    clearReconnectTimer(session);
    startHeartbeat(session);
    const wasDown = session.reconnectAttempts > 0 || session.reconnectNotice;
    session.reconnectAttempts = 0;
    session.reconnectNotice = false;
    if (wasDown && session.id === activeSessionId) {
      session.term.write(`\r\n\x1b[2m[${t("terminal.reconnected")}]\x1b[0m\r\n`);
    }
    if (session.id === activeSessionId) sendResize(session);
    flushPendingInput(session);
    if (session.id === activeSessionId) session.term.focus();
  });
  socket.addEventListener("message", (ev) => {
    if (isControlMessage(ev.data)) return;
    let chunk;
    if (ev.data instanceof ArrayBuffer) {
      chunk = new Uint8Array(ev.data);
    } else if (ev.data instanceof Blob) {
      ev.data.arrayBuffer().then((buf) => {
        const bytes = new Uint8Array(buf);
        session.term.write(bytes);
        appendOutputBuffer(session, new TextDecoder().decode(bytes));
      });
      return;
    } else {
      chunk = String(ev.data);
      session.term.write(chunk);
      appendOutputBuffer(session, chunk);
      return;
    }
    session.term.write(chunk);
    appendOutputBuffer(session, new TextDecoder().decode(chunk));
  });
  socket.addEventListener("close", () => {
    stopHeartbeat(session);
    if (session.socket === socket) session.socket = null;
    scheduleReconnect(session);
  });
  socket.addEventListener("error", () => {
    // error 后浏览器会紧跟 close 事件，重连交由 close 处理，这里不再打印，避免噪音
  });
}

function disconnectSession(session) {
  session.pendingInput = null;
  session.reconnectNotice = false;
  session.manualClose = true;
  stopHeartbeat(session);
  clearReconnectTimer(session);
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
  attachTerminalLinks(term);

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
    reconnectAttempts: 0,
    reconnectTimer: null,
    heartbeatTimer: null,
    manualClose: false,
    outputBuffer: "",
    lastErrorText: null,
  };

  term.onData((data) => sendInput(session, data));
  term.onResize(() => {
    if (session.id === activeSessionId) sendResize(session);
  });
  bindSelectionActions(session);

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
  // 切回/打开一个已掉线的会话时，重置退避并立即重连
  if (!session.socket) {
    clearReconnectTimer(session);
    session.reconnectAttempts = 0;
    connectSession(session);
  }
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

  window.addEventListener("auc-locale-change", () => {
    renderTabs();
    const auto = $("#terminal-auto-agent");
    if (auto) auto.checked = isAutoAgentEnabled();
  });
  bindTerminalActionBar();
}
