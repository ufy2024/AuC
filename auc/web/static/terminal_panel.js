/** Code 模式底部终端（xterm.js ESM + WebSocket PTY） */

const $ = (sel) => document.querySelector(sel);

const XTERM_MOD = new URL("./vendor/xterm.esm.js?v=22", import.meta.url);
const FIT_MOD = new URL("./vendor/addon-fit.esm.js?v=22", import.meta.url);

let term = null;
let fitAddon = null;
let socket = null;
let resizeObserver = null;
let pendingInput = null;
let reconnectNotice = false;
let xtermLibs = null;
let xtermLoading = null;

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

function showTerminalLoadError(host, message) {
  host.innerHTML = `<div class="terminal-load-error">${message}</div>`;
}

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/api/terminal/ws`;
}

function sendResize() {
  if (!term || !socket || socket.readyState !== WebSocket.OPEN) return;
  try {
    fitAddon?.fit();
  } catch {
    /* host may have zero size during layout */
  }
  socket.send(
    JSON.stringify({
      type: "resize",
      cols: term.cols || 80,
      rows: term.rows || 24,
    }),
  );
}

function flushPendingInput() {
  if (!pendingInput || !socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(pendingInput);
  pendingInput = null;
}

function sendInput(data) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    pendingInput = data;
    connectTerminal();
    return;
  }
  socket.send(data);
}

function connectTerminal() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  socket = new WebSocket(wsUrl());
  socket.binaryType = "arraybuffer";
  socket.addEventListener("open", () => {
    reconnectNotice = false;
    sendResize();
    flushPendingInput();
    term?.focus();
  });
  socket.addEventListener("message", (ev) => {
    if (!term) return;
    if (ev.data instanceof ArrayBuffer) {
      term.write(new Uint8Array(ev.data));
    } else if (ev.data instanceof Blob) {
      ev.data.arrayBuffer().then((buf) => term.write(new Uint8Array(buf)));
    } else {
      term.write(String(ev.data));
    }
  });
  socket.addEventListener("close", () => {
    socket = null;
    if (term && isTerminalOpen() && !reconnectNotice) {
      reconnectNotice = true;
      term.write("\r\n\x1b[33m[终端已断开，继续输入将自动重连]\x1b[0m\r\n");
    }
  });
  socket.addEventListener("error", () => {
    term?.write("\r\n\x1b[31m[终端连接失败]\x1b[0m\r\n");
  });
}

function disconnectTerminal() {
  pendingInput = null;
  reconnectNotice = false;
  if (socket) {
    socket.close();
    socket = null;
  }
}

async function ensureTerminal() {
  if (term) return true;
  const host = $("#terminal-host");
  if (!host) return false;

  host.querySelector(".terminal-load-error")?.remove();

  let libs;
  try {
    libs = await loadXtermLibs();
  } catch (err) {
    showTerminalLoadError(
      host,
      `终端组件加载失败：${err?.message || err}。请硬刷新（Ctrl+Shift+R）后重试。`,
    );
    return false;
  }

  const { Terminal, FitAddon } = libs;
  term = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: '"JetBrains Mono", "Fira Code", Menlo, Consolas, monospace',
    theme: xtermTheme(),
    allowProposedApi: true,
  });
  if (FitAddon) {
    fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
  }
  term.open(host);
  term.onData((data) => sendInput(data));
  term.onResize(() => sendResize());

  resizeObserver = new ResizeObserver(() => {
    if (isTerminalOpen()) sendResize();
  });
  resizeObserver.observe(host);
  return true;
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
  sendResize();
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
  if (!(await ensureTerminal())) return;
  connectTerminal();
  requestAnimationFrame(() => {
    sendResize();
    term?.focus();
  });
}

export function closeTerminal() {
  const panel = $("#terminal-panel");
  const btn = $("#btn-terminal");
  panel?.classList.remove("is-open");
  panel?.classList.add("is-collapsed");
  btn?.classList.remove("active");
  localStorage.setItem("auc-terminal-open", "0");
  disconnectTerminal();
  window.dispatchEvent(new Event("auc-terminal-resize"));
}

export function toggleTerminal() {
  if (isTerminalOpen()) closeTerminal();
  else void openTerminal();
}

export function refreshTerminalTheme() {
  if (!term) return;
  term.options.theme = xtermTheme();
}

export function initTerminalPanel() {
  const panel = $("#terminal-panel");
  if (!panel) return;

  const savedH = parseInt(localStorage.getItem("auc-terminal-height") || "240", 10);
  panel.style.setProperty("--terminal-height", `${savedH}px`);

  $("#btn-terminal")?.addEventListener("click", () => toggleTerminal());
  $("#terminal-close")?.addEventListener("click", () => closeTerminal());
  $("#terminal-new")?.addEventListener("click", () => {
    disconnectTerminal();
    term?.clear();
    connectTerminal();
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

  if (localStorage.getItem("auc-terminal-open") === "1") {
    void openTerminal();
  } else {
    panel.classList.add("is-collapsed");
  }

  window.addEventListener("resize", () => {
    if (isTerminalOpen()) sendResize();
  });
}
