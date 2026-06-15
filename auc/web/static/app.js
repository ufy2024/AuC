/** AuC Web — Code (JupyterLab) + Chat (简约) 双模式 */

import {
  buildMessageContent,
  renderMermaidIn,
  replaceMermaidInText,
} from "./message_render.js";
import {
  COLOR_THEMES,
  ICON_THEMES,
  loadStoredColorTheme,
  loadStoredIconTheme,
  applyColorTheme,
  applyIconTheme,
  isColorThemeDark,
  monacoThemeFor,
} from "./themes.js";
import { materialIconImg } from "./material_file_icons.js";
import {
  icon,
  setButtonIcon,
  setActiveIconTheme,
  treeEntryIconParts,
} from "./icons.js";
import {
  initTerminalPanel,
  refreshTerminalTheme,
  isTerminalOpen,
} from "./terminal_panel.js";

const $ = (sel) => document.querySelector(sel);
const state = {
  mode: localStorage.getItem("auc-mode") || "code",
  info: null,
  treePath: ".",
  openTabs: [],
  activeTab: null,
  editor: null,
  monacoReady: false,
  streaming: false,
  abort: null,
  attachments: { agent: [], chat: [] },
  projects: [],
  previewUrl: null,
  previewTitle: "",
  activeRunId: null,
  autoAttach: localStorage.getItem("auc-auto-attach") !== "0",
  workMode: localStorage.getItem("auc-work-mode") || "auto",
  workModes: [],
  roleId: localStorage.getItem("auc-role") || "coder",
  roles: [],
  activeConversationId: null,
  conversations: [],
  fileCache: {},
  mdViewMode: localStorage.getItem("auc-md-view") || "preview",
  sidebarHidden: localStorage.getItem("auc-sidebar-hidden") === "1",
  sidebarSections: {
    workspace: localStorage.getItem("auc-sec-workspace") !== "0",
    projects: localStorage.getItem("auc-sec-projects") !== "0",
    conversations: localStorage.getItem("auc-sec-conversations") !== "0",
  },
  colorTheme: loadStoredColorTheme(),
  iconTheme: loadStoredIconTheme(),
};

// ── 侧栏折叠 / 隐藏 ──
function applySidebarState() {
  const app = $("#app");
  if (!app) return;
  app.classList.toggle("sidebar-hidden", state.sidebarHidden);
  for (const [name, open] of Object.entries(state.sidebarSections)) {
    const sec = document.querySelector(`.sidebar-section[data-section="${name}"]`);
    const toggle = document.querySelector(`.section-toggle[data-section="${name}"]`);
    if (sec) sec.classList.toggle("is-collapsed", !open);
    if (toggle) {
      toggle.classList.toggle("is-collapsed", !open);
      setButtonIcon(toggle, open ? "chevronUp" : "chevronDown", { size: 14 });
      toggle.title = open ? "折叠" : "展开";
    }
  }
}

function toggleSidebarSection(name) {
  if (!Object.hasOwn(state.sidebarSections, name)) return;
  state.sidebarSections[name] = !state.sidebarSections[name];
  localStorage.setItem(`auc-sec-${name}`, state.sidebarSections[name] ? "1" : "0");
  applySidebarState();
}

function setSidebarHidden(hidden) {
  state.sidebarHidden = hidden;
  localStorage.setItem("auc-sidebar-hidden", hidden ? "1" : "0");
  applySidebarState();
}

function showSidebarWithSection(name) {
  setSidebarHidden(false);
  if (name && Object.hasOwn(state.sidebarSections, name)) {
    state.sidebarSections[name] = true;
    localStorage.setItem(`auc-sec-${name}`, "1");
  }
  applySidebarState();
}

function initSidebarChrome() {
  const secIcons = {
    workspace: "folder",
    projects: "rocket",
    conversations: "message",
  };
  for (const [id, ic] of Object.entries(secIcons)) {
    const el = $(`#icon-sec-${id}`);
    if (el) el.innerHTML = icon(ic, { size: 14 });
  }
  setButtonIcon($("#sidebar-hide"), "panelLeftClose", { size: 18 });
  setButtonIcon($("#sidebar-show"), "chevronRight", { size: 18 });
  setButtonIcon($("#btn-terminal"), "terminal", { size: 16 });
  setButtonIcon($("#terminal-close"), "chevronDown", { size: 15 });
  setButtonIcon($("#terminal-new"), "plus", { size: 14 });
  setButtonIcon($("#terminal-picker"), "chevronDown", { size: 14 });
  setButtonIcon($("#ws-new-file"), "filePlus", { size: 15 });
  setButtonIcon($("#ws-new-folder"), "folderPlus", { size: 15 });
  setButtonIcon($("#ws-refresh"), "refresh", { size: 15 });
  setButtonIcon($("#projects-refresh"), "refresh", { size: 15 });
  setButtonIcon($("#conv-new"), "plus", { size: 15 });
  setButtonIcon($("#chat-clear"), "trash", { size: 15 });
  setButtonIcon($("#btn-clear-chat"), "trash", { size: 16 });
  setButtonIcon($("#btn-attach-agent"), "image", { size: 18 });
  setButtonIcon($("#btn-attach-chat"), "image", { size: 18 });

  document.querySelectorAll("[data-rail-section]").forEach((btn) => {
    const map = { workspace: "folder", projects: "rocket", conversations: "message" };
    setButtonIcon(btn, map[btn.dataset.railSection], { size: 18 });
  });

  $("#sidebar-hide")?.addEventListener("click", () => setSidebarHidden(true));
  $("#sidebar-show")?.addEventListener("click", () => setSidebarHidden(false));
  document.querySelectorAll("[data-rail-section]").forEach((btn) => {
    btn.addEventListener("click", () => showSidebarWithSection(btn.dataset.railSection));
  });

  document.querySelectorAll(".section-toggle").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      toggleSidebarSection(btn.dataset.section);
    });
  });
  document.querySelectorAll(".section-head").forEach((head) => {
    head.addEventListener("click", (ev) => {
      if (ev.target.closest(".section-actions")) return;
      const sec = head.closest(".sidebar-section")?.dataset.section;
      if (sec) toggleSidebarSection(sec);
    });
  });

  document.querySelectorAll(".section-actions .icon-btn").forEach((btn) => {
    if (btn.classList.contains("section-toggle")) return;
    btn.addEventListener("click", (ev) => ev.stopPropagation());
  });

  applySidebarState();
}

// ── 主题（颜色 / 图标，类似 VS Code） ──
function applyMonacoTheme() {
  if (state.monacoReady && typeof monaco !== "undefined") {
    monaco.editor.setTheme(monacoThemeFor(state.colorTheme));
  }
}

function refreshThemePickerUI() {
  document.querySelectorAll("[data-color-theme-id]").forEach((el) => {
    const active = el.dataset.colorThemeId === state.colorTheme;
    el.classList.toggle("is-active", active);
    const check = el.querySelector(".theme-check");
    if (check) check.innerHTML = active ? icon("check", { size: 14 }) : "";
  });
  document.querySelectorAll("[data-icon-theme-id]").forEach((el) => {
    const active = el.dataset.iconThemeId === state.iconTheme;
    el.classList.toggle("is-active", active);
    const check = el.querySelector(".theme-check");
    if (check) check.innerHTML = active ? icon("check", { size: 14 }) : "";
  });
}

function closeThemeMenu() {
  $("#theme-picker-menu")?.classList.add("hidden");
  $("#theme-picker-btn")?.setAttribute("aria-expanded", "false");
}

function toggleThemeMenu() {
  const menu = $("#theme-picker-menu");
  if (!menu) return;
  const willOpen = menu.classList.contains("hidden");
  if (willOpen) {
    menu.classList.remove("hidden");
    $("#theme-picker-btn")?.setAttribute("aria-expanded", "true");
    refreshThemePickerUI();
  } else {
    closeThemeMenu();
  }
}

async function selectColorTheme(id) {
  if (id === state.colorTheme) return;
  state.colorTheme = applyColorTheme(id);
  applyMonacoTheme();
  refreshTerminalTheme();
  refreshThemePickerUI();
  if (state.info?.conversation?.messages) {
    await renderChatHistory(state.info.conversation.messages);
  }
}

function selectIconTheme(id) {
  if (id === state.iconTheme) return;
  state.iconTheme = applyIconTheme(id);
  setActiveIconTheme(id);
  refreshThemePickerUI();
  initSidebarChrome();
  loadTree(state.treePath).catch(() => {});
}

function buildThemePicker() {
  const colorList = $("#color-theme-list");
  const iconList = $("#icon-theme-list");
  if (!colorList || !iconList) return;

  colorList.replaceChildren();
  for (const t of COLOR_THEMES) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "theme-item";
    btn.dataset.colorThemeId = t.id;
    btn.setAttribute("role", "menuitemradio");
    const swatches = t.preview
      .map((c) => `<span style="background:${c}"></span>`)
      .join("");
    btn.innerHTML = `
      <span class="theme-preview">${swatches}</span>
      <span class="theme-item-text">
        <span class="theme-item-label">${t.label}</span>
        <span class="theme-item-desc">${t.description}</span>
      </span>
      <span class="theme-check"></span>`;
    btn.addEventListener("click", () => selectColorTheme(t.id));
    colorList.appendChild(btn);
  }

  iconList.replaceChildren();
  for (const t of ICON_THEMES) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "theme-item";
    btn.dataset.iconThemeId = t.id;
    btn.setAttribute("role", "menuitemradio");
    const previews = t.preview
      .map((n) => {
        if (n.startsWith("material:")) {
          return materialIconImg(n.slice(9), { size: 14 });
        }
        return icon(n, { size: 14, theme: t.id });
      })
      .join("");
    btn.innerHTML = `
      <span class="theme-preview-icons">${previews}</span>
      <span class="theme-item-text">
        <span class="theme-item-label">${t.label}</span>
        <span class="theme-item-desc">${t.description}</span>
      </span>
      <span class="theme-check"></span>`;
    btn.addEventListener("click", () => selectIconTheme(t.id));
    iconList.appendChild(btn);
  }

  setButtonIcon($("#theme-picker-btn"), "palette", { size: 18 });
  $("#theme-picker-btn")?.addEventListener("click", (ev) => {
    ev.stopPropagation();
    toggleThemeMenu();
  });
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest("#theme-picker-wrap")) closeThemeMenu();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closeThemeMenu();
  });
  refreshThemePickerUI();
}

function initThemes() {
  state.colorTheme = applyColorTheme(loadStoredColorTheme());
  state.iconTheme = applyIconTheme(loadStoredIconTheme());
  setActiveIconTheme(state.iconTheme);
  buildThemePicker();
}

// ── 模式（仅布局，颜色由 color theme 决定） ──
function setMode(mode) {
  state.mode = mode;
  localStorage.setItem("auc-mode", mode);
  const app = $("#app");
  app.classList.remove("mode-code", "mode-chat");
  app.classList.add(`mode-${mode}`);
  document.querySelectorAll(".mode-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
  });
}

document.querySelectorAll(".mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => setMode(btn.dataset.mode));
});

// ── API ──
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || res.statusText);
  }
  return res.json();
}

function currentRoleSpec() {
  return state.roles.find((r) => r.id === state.roleId) || state.roles[0] || null;
}

function roleLabel(id) {
  const r = state.roles.find((x) => x.id === id);
  return r ? r.label : id;
}

function renderAgentProfile(info = state.info) {
  if (!info) return;
  const agent = info.agent || {};
  const role = currentRoleSpec();
  const title = $("#agent-title");
  const desc = $("#agent-desc");
  const status = $("#agent-status");
  const meta = $("#agent-meta");
  const tags = $("#agent-tags");
  if (!title) return;

  title.textContent = role?.label || agent.name || "Coder 专家";
  if (desc) {
    desc.textContent =
      role?.description || agent.description || agent.title || "编程、调试与架构设计助手";
  }
  if (status) {
    if (state.streaming) {
      status.textContent = "思考中";
      status.className = "agent-status busy";
    } else {
      status.textContent = (info.turns || 0) > 0 ? "在线" : "就绪";
      status.className = "agent-status";
    }
  }
  if (meta) {
    const items = [
      { k: "模型", v: `${info.model?.provider || "?"} / ${info.model?.model || "?"}` },
      { k: "角色", v: roleLabel(state.roleId) },
      { k: "模式", v: workModeLabel(state.workMode) },
      { k: "工作区", v: info.workspace?.display || "." },
      { k: "对话", v: `${info.turns || 0} 轮` },
    ];
    if (info.evolve) items.push({ k: "进化", v: "已开启" });
    meta.innerHTML = items
      .map((it) => `<span class="agent-meta-item"><em>${it.k}</em>${escapeHtml(it.v)}</span>`)
      .join("");
  }
  if (tags) {
    const caps = role?.capabilities || agent.capabilities || ["代码编辑", "文件读写", "Mermaid 图表"];
    tags.innerHTML = caps.map((c) => `<span class="agent-tag">${escapeHtml(c)}</span>`).join("");
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function workModeLabel(id) {
  const m = state.workModes.find((x) => x.id === id);
  return m ? m.label : id;
}

function populateWorkModeSelects() {
  const modes = state.workModes.length
    ? state.workModes
    : [{ id: "auto", label: "自动识别", description: "" }];
  for (const sel of ["#work-mode-select", "#work-mode-agent"]) {
    const el = $(sel);
    if (!el) continue;
    const prev = el.value || state.workMode;
    el.innerHTML = modes
      .map(
        (m) =>
          `<option value="${escapeHtml(m.id)}" title="${escapeHtml(m.description || "")}">${escapeHtml(m.label)}</option>`
      )
      .join("");
    el.value = modes.some((m) => m.id === prev) ? prev : "auto";
  }
  setWorkMode($("#work-mode-select")?.value || state.workMode, { persist: false });
}

function setWorkMode(mode, { persist = true } = {}) {
  state.workMode = mode || "auto";
  if (persist) localStorage.setItem("auc-work-mode", state.workMode);
  for (const sel of ["#work-mode-select", "#work-mode-agent"]) {
    const el = $(sel);
    if (el && el.value !== state.workMode) el.value = state.workMode;
  }
  renderAgentProfile(state.info);
}

function bindWorkModeSelects() {
  for (const sel of ["#work-mode-select", "#work-mode-agent"]) {
    const el = $(sel);
    if (!el || el.dataset.bound) continue;
    el.dataset.bound = "1";
    el.addEventListener("change", () => setWorkMode(el.value));
  }
}

function populateRoleSelects() {
  const roles = state.roles.length
    ? state.roles
    : [{ id: "coder", label: "编程专家", description: "" }];
  for (const sel of ["#role-select", "#role-agent"]) {
    const el = $(sel);
    if (!el) continue;
    const prev = el.value || state.roleId;
    el.innerHTML = roles
      .map(
        (r) =>
          `<option value="${escapeHtml(r.id)}" title="${escapeHtml(r.description || r.title || "")}">${escapeHtml(r.label)}</option>`
      )
      .join("");
    el.value = roles.some((r) => r.id === prev) ? prev : "coder";
  }
  setRole($("#role-select")?.value || state.roleId, { persist: false });
}

function setRole(role, { persist = true } = {}) {
  state.roleId = role || "coder";
  if (persist) localStorage.setItem("auc-role", state.roleId);
  for (const sel of ["#role-select", "#role-agent"]) {
    const el = $(sel);
    if (el && el.value !== state.roleId) el.value = state.roleId;
  }
  renderAgentProfile(state.info);
}

function bindRoleSelects() {
  for (const sel of ["#role-select", "#role-agent"]) {
    const el = $(sel);
    if (!el || el.dataset.bound) continue;
    el.dataset.bound = "1";
    el.addEventListener("change", () => setRole(el.value));
  }
}

async function loadInfo() {
  state.info = await api("/api/info");
  state.workModes = state.info.work_modes || [];
  state.roles = state.info.roles || [];
  const activeFromApi = state.info.roles?.find((r) => r.active);
  if (activeFromApi) {
    state.roleId = activeFromApi.id;
    localStorage.setItem("auc-role", state.roleId);
  } else if (state.info.agent?.active_role) {
    state.roleId = state.info.agent.active_role;
  } else if (state.info.agent?.role_default && !localStorage.getItem("auc-role")) {
    state.roleId = state.info.agent.role_default;
  }
  state.activeConversationId = state.info.conversation?.active_id || null;
  renderVersionInfo(state.info);
  $("#model-pill").textContent = `${state.info.model.provider} / ${state.info.model.model}`;
  $("#ws-pill").textContent = state.info.workspace.display;
  populateWorkModeSelects();
  bindWorkModeSelects();
  populateRoleSelects();
  bindRoleSelects();
  renderAgentProfile(state.info);
  if (state.info.conversation?.messages) {
    await renderChatHistory(state.info.conversation.messages);
  }
  await loadConversations();
}

function renderVersionInfo(info) {
  const versionEl = $("#version");
  const release = info.release || {};
  const current = release.current_version || info.version || "";
  if (versionEl) {
    versionEl.textContent = `v${current}`;
    versionEl.classList.toggle("has-update", !!release.update_available);
    if (release.update_available && release.latest_version) {
      versionEl.title = `当前 v${current}，PyPI 最新 v${release.latest_version}，建议升级`;
    } else {
      versionEl.title = `当前版本 v${current}`;
    }
  }
  renderUpdateNotices(release);
}

function isUpdateDismissed(release) {
  if (!release?.latest_version) return true;
  return localStorage.getItem(`auc-update-dismiss-${release.latest_version}`) === "1";
}

function updateNoticeCopy(release) {
  const current = release.current_version || "";
  const latest = release.latest_version || "";
  const cmd = release.install_cmd || "pip install -U ufy-auc";
  return {
    headline: `检测到新版本：PyPI 已发布 v${latest}，您当前运行 v${current}。`,
    detail: "建议尽快升级以获得最新功能、修复与 Web 界面改进。",
    cmd,
    chatHeadline: `AuC 有新版本可用（v${latest}），当前为 v${current}。`,
    chatDetail: `请在终端执行以下命令完成升级：`,
  };
}

function dismissUpdateNotice(release) {
  if (release?.latest_version) {
    localStorage.setItem(`auc-update-dismiss-${release.latest_version}`, "1");
  }
  $("#update-banner")?.classList.add("hidden");
  $("#chat-update-notice")?.classList.add("hidden");
  $("#chat-update-msg")?.remove();
}

function renderUpdateNotices(release) {
  const banner = $("#update-banner");
  const chatNotice = $("#chat-update-notice");
  const chatMessages = $("#chat-messages");

  if (!release?.update_available || !release.latest_version || isUpdateDismissed(release)) {
    banner?.classList.add("hidden");
    chatNotice?.classList.add("hidden");
    $("#chat-update-msg")?.remove();
    return;
  }

  const copy = updateNoticeCopy(release);

  if (banner) {
    const text = $("#update-banner-text");
    const cmd = $("#update-banner-cmd");
    const link = $("#update-banner-link");
    if (text) text.textContent = `${copy.headline} ${copy.detail}`;
    if (cmd) cmd.textContent = copy.cmd;
    if (link && release.pypi_url) link.href = release.pypi_url;
    banner.classList.remove("hidden");
  }

  if (chatNotice) {
    const text = $("#chat-update-text");
    const hint = $("#chat-update-hint");
    if (text) text.textContent = copy.chatHeadline;
    if (hint) {
      hint.innerHTML = `${copy.chatDetail} <code>${copy.cmd}</code>`;
    }
    chatNotice.classList.remove("hidden");
  }

  if (chatMessages) {
    let msg = $("#chat-update-msg");
    if (!msg) {
      msg = document.createElement("div");
      msg.id = "chat-update-msg";
      msg.className = "msg msg-note update-msg";
      chatMessages.prepend(msg);
    }
    msg.innerHTML =
      `<div class="update-msg-title">版本更新提示</div>` +
      `<p class="update-msg-body">${copy.chatHeadline} ${copy.chatDetail}</p>` +
      `<code class="update-msg-cmd">${copy.cmd}</code>`;
  }
}

function bindUpdateBanner() {
  const dismiss = () => dismissUpdateNotice(state.info?.release);
  $("#update-banner-dismiss")?.addEventListener("click", dismiss);
  $("#chat-update-dismiss")?.addEventListener("click", dismiss);
}

// ── 模型配置（顶栏 model-pill） ──
let modelSettingsCache = null;
let modelKeyVisible = false;

function setModelKeyVisible(visible) {
  modelKeyVisible = !!visible;
  const input = $("#model-settings-api-key");
  const btn = $("#model-settings-key-toggle");
  if (input) input.type = modelKeyVisible ? "text" : "password";
  if (btn) {
    btn.setAttribute("aria-pressed", modelKeyVisible ? "true" : "false");
    btn.title = modelKeyVisible ? "隐藏密钥" : "显示密钥";
    btn.setAttribute("aria-label", btn.title);
    setButtonIcon(btn, modelKeyVisible ? "eyeOff" : "eye", { size: 16 });
  }
}

function hideModelSettings() {
  $("#model-settings-overlay")?.classList.add("hidden");
  $("#model-settings-error")?.classList.add("hidden");
  setModelKeyVisible(false);
  const input = $("#model-settings-api-key");
  if (input) input.value = "";
}

function renderModelLayers(s) {
  const layers = s.layers || {};
  const activeScope = s.active_scope || layers.active_scope;
  const scopeLabels = {
    global: "全局",
    project: "项目共享",
    project_local: "项目本地",
  };
  const activeEl = $("#model-settings-active-scope");
  if (activeEl) {
    activeEl.textContent = scopeLabels[activeScope] || activeScope || "默认";
  }
  const note = $("#model-settings-layers");
  if (note) {
    const globalFiles = (layers.global_files || []).filter((f) => f.exists).map((f) => f.path);
    const projectFiles = (layers.project_files || []).filter((f) => f.exists).map((f) => f.path);
    const parts = [];
    if (globalFiles.length) parts.push(`全局：${globalFiles.map((p) => p.split("/").slice(-2).join("/")).join("、")}`);
    if (projectFiles.length) parts.push(`项目：${projectFiles.map((p) => p.split("/").slice(-2).join("/")).join("、")}`);
    note.textContent = parts.length
      ? `${parts.join("  →  ")}（后者覆盖前者）`
      : "尚未发现配置文件，保存后将创建对应层级。";
  }
  const scopeSel = $("#model-settings-scope");
  const scopeHint = $("#model-settings-scope-hint");
  if (scopeSel && layers.save_scopes) {
    const preferred = activeScope && activeScope !== "global" ? activeScope : "project_local";
    scopeSel.value = ["global", "project", "project_local"].includes(preferred) ? preferred : "project_local";
    updateModelScopeHint(layers.save_scopes, scopeSel.value);
  } else if (scopeHint) {
    scopeHint.textContent = layers.priority_note || "";
  }
}

function updateModelScopeHint(saveScopes, scopeId) {
  const hint = $("#model-settings-scope-hint");
  if (!hint) return;
  const row = (saveScopes || []).find((s) => s.id === scopeId);
  hint.textContent = row?.hint || row?.path || "";
}

async function openModelSettings() {
  const overlay = $("#model-settings-overlay");
  if (!overlay) return;
  try {
    modelSettingsCache = await api("/api/settings/model");
  } catch (err) {
    alert(`加载模型配置失败：${err.message}`);
    return;
  }
  const s = modelSettingsCache;
  $("#model-settings-provider").value = s.provider || "openai";
  $("#model-settings-model").value = s.model || "";
  $("#model-settings-base-url").value = s.base_url || "";
  $("#model-settings-api-key").value = s.api_key || "";
  setModelKeyVisible(false);
  renderModelLayers(s);
  const hint = $("#model-settings-key-hint");
  if (hint) {
    hint.textContent = s.api_key_set
      ? `已配置（${s.api_key_masked}），点击右侧眼睛可查看完整密钥`
      : "尚未配置 API Key";
  }
  overlay.classList.remove("hidden");
  $("#model-settings-model")?.focus();
}

async function saveModelSettings() {
  const errEl = $("#model-settings-error");
  errEl?.classList.add("hidden");
  const body = {
    provider: $("#model-settings-provider")?.value || "openai",
    model: $("#model-settings-model")?.value?.trim() || "",
    base_url: $("#model-settings-base-url")?.value?.trim() || "",
    scope: $("#model-settings-scope")?.value || "project_local",
  };
  const key = $("#model-settings-api-key")?.value?.trim();
  if (key) body.api_key = key;
  try {
    const data = await api("/api/settings/model", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    modelSettingsCache = data;
    if (state.info) {
      state.info.model = {
        ...state.info.model,
        provider: data.provider,
        model: data.model,
        configName: data.config_name,
        configId: data.config_id,
      };
      $("#model-pill").textContent = `${data.provider} / ${data.model}`;
      renderAgentProfile(state.info);
    }
    hideModelSettings();
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message || String(err);
      errEl.classList.remove("hidden");
    }
  }
}

function applyAilabPreset() {
  $("#model-settings-provider").value = "openai";
  $("#model-settings-model").value = "DeepSeek";
  $("#model-settings-base-url").value = "http://ailab.hcrdi.com/api";
}

function bindModelSettings() {
  setButtonIcon($("#model-settings-key-toggle"), "eye", { size: 16 });
  $("#model-pill")?.addEventListener("click", () => void openModelSettings());
  $("#model-settings-cancel")?.addEventListener("click", hideModelSettings);
  $("#model-settings-save")?.addEventListener("click", () => void saveModelSettings());
  $("#model-settings-ailab-preset")?.addEventListener("click", applyAilabPreset);
  $("#model-settings-scope")?.addEventListener("change", (ev) => {
    const scopes = modelSettingsCache?.layers?.save_scopes;
    updateModelScopeHint(scopes, ev.target.value);
  });
  $("#model-settings-key-toggle")?.addEventListener("click", () => {
    setModelKeyVisible(!modelKeyVisible);
    $("#model-settings-api-key")?.focus();
  });
  $("#model-settings-overlay")?.addEventListener("click", (ev) => {
    if (ev.target.id === "model-settings-overlay") hideModelSettings();
  });
}

async function refreshAgentStats() {
  try {
    const info = await api("/api/info");
    state.info = { ...state.info, ...info };
    renderVersionInfo(state.info);
    renderAgentProfile(state.info);
  } catch { /* ignore */ }
}

// ── 工作区树 ──
let wsRenameEntry = null;
let treeContextEntry = null;

function workspaceParentPath(relPath) {
  const parts = relPath.split("/").filter(Boolean);
  parts.pop();
  return parts.length ? parts.join("/") : ".";
}

function remapPathsAfterRename(oldPath, newPath) {
  const mapPath = (p) => {
    if (p === oldPath) return newPath;
    if (p.startsWith(`${oldPath}/`)) return newPath + p.slice(oldPath.length);
    return p;
  };
  state.openTabs = [...new Set(state.openTabs.map(mapPath))];
  if (state.activeTab) state.activeTab = mapPath(state.activeTab);
  if (state.fileCache) {
    const next = {};
    for (const [k, v] of Object.entries(state.fileCache)) {
      next[mapPath(k)] = v;
    }
    state.fileCache = next;
  }
  if (state._dirty) {
    const next = {};
    for (const [k, v] of Object.entries(state._dirty)) {
      next[mapPath(k)] = v;
    }
    state._dirty = next;
  }
  renderTabs();
}

function removePathsAfterDelete(targetPath, isDir) {
  const matches = (p) => p === targetPath || (isDir && p.startsWith(`${targetPath}/`));
  state.openTabs = state.openTabs.filter((p) => !matches(p));
  if (state.fileCache) {
    for (const k of Object.keys(state.fileCache)) {
      if (matches(k)) delete state.fileCache[k];
    }
  }
  if (state._dirty) {
    for (const k of Object.keys(state._dirty)) {
      if (matches(k)) delete state._dirty[k];
    }
  }
  if (state.activeTab && matches(state.activeTab)) {
    state.activeTab = state.openTabs[0] || null;
    if (!state.activeTab) {
      $("#app").classList.remove("has-editor");
      hideImagePreview();
      hideAppPreview();
      hideMdPreview();
      state.editor?.dispose();
      state.editor = null;
    } else {
      openFile(state.activeTab);
    }
  }
  renderTabs();
}

function hideTreeContextMenu() {
  $("#tree-context-menu")?.classList.add("hidden");
  treeContextEntry = null;
}

function showTreeContextMenu(ev, entry) {
  const menu = $("#tree-context-menu");
  if (!menu) return;
  ev.preventDefault();
  treeContextEntry = entry;
  menu.innerHTML = `
    <button type="button" data-action="rename">重命名</button>
    <button type="button" data-action="delete" class="danger">删除</button>`;
  menu.classList.remove("hidden");
  menu.style.left = `${ev.clientX}px`;
  menu.style.top = `${ev.clientY}px`;
  menu.querySelector('[data-action="rename"]')?.addEventListener("click", () => {
    hideTreeContextMenu();
    showWsRenameDialog(entry);
  });
  menu.querySelector('[data-action="delete"]')?.addEventListener("click", () => {
    hideTreeContextMenu();
    deleteWorkspaceEntry(entry);
  });
}

async function deleteWorkspaceEntry(entry) {
  const label = entry.type === "dir" ? "文件夹" : "文件";
  const ok = window.confirm(`确定删除${label}「${entry.name}」？此操作不可撤销。`);
  if (!ok) return;
  try {
    await api(`/api/workspace/path?path=${encodeURIComponent(entry.path)}`, {
      method: "DELETE",
    });
    removePathsAfterDelete(entry.path, entry.type === "dir");
    await loadTree(state.treePath);
  } catch (e) {
    window.alert(e.message || "删除失败");
  }
}

function showWsRenameDialog(entry) {
  wsRenameEntry = entry;
  const overlay = $("#ws-create-overlay");
  const title = $("#ws-create-title");
  const hint = $("#ws-create-hint");
  const input = $("#ws-create-input");
  const err = $("#ws-create-error");
  const confirmBtn = $("#ws-create-confirm");
  if (!overlay || !input) return;
  wsCreateMode = "rename";
  if (title) title.textContent = "重命名";
  if (hint) hint.textContent = `原名称：${entry.name}`;
  if (confirmBtn) confirmBtn.textContent = "确定";
  if (err) {
    err.textContent = "";
    err.classList.add("hidden");
  }
  input.value = entry.name;
  overlay.classList.remove("hidden");
  input.focus();
  input.select();
}

async function loadTree(path = ".") {
  state.treePath = path;
  $("#ws-path").textContent = path;
  const data = await api(`/api/workspace/tree?path=${encodeURIComponent(path)}`);
  const root = $("#file-tree");
  root.innerHTML = "";
  if (path !== ".") {
    const up = document.createElement("div");
    up.className = "tree-item";
    up.innerHTML = `<span class="tree-icon">${icon("arrowUp", { size: 14 })}</span><span>..</span>`;
    up.addEventListener("click", () => {
      const parts = path.split("/").filter(Boolean);
      parts.pop();
      loadTree(parts.length ? parts.join("/") : ".");
    });
    root.appendChild(up);
  }
  for (const e of data.entries) {
    const row = document.createElement("div");
    row.className = "tree-item";
    if (state.activeTab === e.path) row.classList.add("active");
    const { html: icHtml, treeClass } = treeEntryIconParts(e, { size: 14 });
    const treeCls = treeClass ? ` ${treeClass}` : "";
    row.innerHTML = `
      <span class="tree-icon${treeCls}">${icHtml}</span>
      <span class="tree-name">${e.name}</span>
      <span class="tree-actions">
        <button type="button" class="icon-btn tree-action-rename" title="重命名"></button>
        <button type="button" class="icon-btn tree-action-delete" title="删除"></button>
      </span>`;
    setButtonIcon(row.querySelector(".tree-action-rename"), "pencil", { size: 12 });
    setButtonIcon(row.querySelector(".tree-action-delete"), "trash", { size: 12 });
    row.querySelector(".tree-action-rename")?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      showWsRenameDialog(e);
    });
    row.querySelector(".tree-action-delete")?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      deleteWorkspaceEntry(e);
    });
    row.addEventListener("contextmenu", (ev) => showTreeContextMenu(ev, e));
    row.addEventListener("click", (ev) => {
      if (ev.target.closest(".tree-actions")) return;
      if (e.type === "dir") loadTree(e.path);
      else if (e.is_html && ev.altKey) openHtmlPreview(e.path, e.name);
      else if (e.is_html) openHtmlPreview(e.path, e.name);
      else openFile(e.path);
    });
    root.appendChild(row);
  }
}

document.addEventListener("click", (ev) => {
  if (!ev.target.closest("#tree-context-menu")) hideTreeContextMenu();
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") hideTreeContextMenu();
});

$("#ws-refresh").addEventListener("click", () => loadTree(state.treePath));

// ── 工作区：新建文件 / 文件夹 ──
let wsCreateMode = null;
let wsCreateResolve = null;

function joinWorkspacePath(parent, name) {
  const n = name.trim();
  if (!n || n === "." || n === ".." || /[\\/]/.test(n)) {
    throw new Error("名称不能包含 / 或 \\，且不能为 . 或 ..");
  }
  if (parent === "." || !parent) return n;
  return `${parent}/${n}`;
}

function showWsCreateDialog(mode) {
  const overlay = $("#ws-create-overlay");
  const title = $("#ws-create-title");
  const hint = $("#ws-create-hint");
  const input = $("#ws-create-input");
  const err = $("#ws-create-error");
  const confirmBtn = $("#ws-create-confirm");
  if (!overlay || !input) return Promise.resolve(null);
  wsCreateMode = mode;
  wsRenameEntry = null;
  if (title) title.textContent = mode === "folder" ? "新建文件夹" : "新建文件";
  if (confirmBtn) confirmBtn.textContent = "创建";
  if (hint) {
    const loc = state.treePath === "." ? "工作区根目录" : state.treePath;
    hint.textContent = `将在 ${loc} 下创建`;
  }
  if (err) {
    err.textContent = "";
    err.classList.add("hidden");
  }
  input.value = mode === "folder" ? "newfolder" : "untitled.txt";
  overlay.classList.remove("hidden");
  input.focus();
  input.select();
  return new Promise((resolve) => {
    wsCreateResolve = resolve;
  });
}

function closeWsCreateDialog(result = null) {
  $("#ws-create-overlay")?.classList.add("hidden");
  wsCreateMode = null;
  wsRenameEntry = null;
  if (wsCreateResolve) {
    wsCreateResolve(result);
    wsCreateResolve = null;
  }
}

async function confirmWsCreate() {
  const input = $("#ws-create-input");
  const err = $("#ws-create-error");
  if (!input || !wsCreateMode) return;

  if (wsCreateMode === "rename") {
    if (!wsRenameEntry) return;
    const newName = input.value.trim();
    if (!newName || newName === wsRenameEntry.name) {
      closeWsCreateDialog(null);
      return;
    }
    let newPath;
    try {
      const parent = workspaceParentPath(wsRenameEntry.path);
      newPath = joinWorkspacePath(parent === "." ? "." : parent, newName);
    } catch (e) {
      if (err) {
        err.textContent = e.message;
        err.classList.remove("hidden");
      }
      return;
    }
    try {
      await api("/api/workspace/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: wsRenameEntry.path, new_path: newPath }),
      });
      const oldPath = wsRenameEntry.path;
      closeWsCreateDialog(newPath);
      remapPathsAfterRename(oldPath, newPath);
      await loadTree(state.treePath);
      if (state.activeTab === newPath) await openFile(newPath);
    } catch (e) {
      if (err) {
        err.textContent = e.message || "重命名失败";
        err.classList.remove("hidden");
      }
    }
    return;
  }

  let rel;
  try {
    rel = joinWorkspacePath(state.treePath, input.value);
  } catch (e) {
    if (err) {
      err.textContent = e.message;
      err.classList.remove("hidden");
    }
    return;
  }
  try {
    if (wsCreateMode === "folder") {
      await api("/api/workspace/mkdir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: rel }),
      });
      closeWsCreateDialog(rel);
      await loadTree(state.treePath);
    } else {
      const exists = await fetch(
        `/api/workspace/file?path=${encodeURIComponent(rel)}`,
      );
      if (exists.ok) {
        if (err) {
          err.textContent = "文件已存在";
          err.classList.remove("hidden");
        }
        return;
      }
      await api("/api/workspace/file", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: rel, content: "" }),
      });
      closeWsCreateDialog(rel);
      await loadTree(state.treePath);
      await openFile(rel);
    }
  } catch (e) {
    if (err) {
      err.textContent = e.message || "创建失败";
      err.classList.remove("hidden");
    }
  }
}

$("#ws-new-file")?.addEventListener("click", () => showWsCreateDialog("file"));
$("#ws-new-folder")?.addEventListener("click", () => showWsCreateDialog("folder"));
$("#ws-create-cancel")?.addEventListener("click", () => closeWsCreateDialog(null));
$("#ws-create-confirm")?.addEventListener("click", () => confirmWsCreate());
$("#ws-create-input")?.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") {
    ev.preventDefault();
    confirmWsCreate();
  } else if (ev.key === "Escape") {
    ev.preventDefault();
    closeWsCreateDialog(null);
  }
});

// ── Monaco 编辑器 ──
function initMonaco() {
  return new Promise((resolve) => {
    require.config({
      paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs" },
    });
    require(["vs/editor/editor.main"], () => {
      state.monacoReady = true;
      applyMonacoTheme();
      resolve();
    });
  });
}

function monacoLang(path) {
  const ext = path.split(".").pop()?.toLowerCase();
  const map = {
    py: "python", js: "javascript", ts: "typescript", json: "json",
    md: "markdown", html: "html", css: "css", yaml: "yaml", yml: "yaml",
    sh: "shell", rs: "rust", go: "go", java: "java",
  };
  return map[ext] || "plaintext";
}

function isMarkdownPath(path) {
  if (!path) return false;
  const ext = path.split(".").pop()?.toLowerCase();
  return ext === "md" || ext === "markdown";
}

function hideMdPreview() {
  $("#md-preview")?.classList.add("hidden");
}

async function showMdPreviewView(content) {
  hideImagePreview();
  hideAppPreview();
  $("#monaco").style.display = "none";
  const box = $("#md-preview");
  if (!box) return;
  box.classList.remove("hidden");
  box.replaceChildren(buildMessageContent(content, { theme: messageTheme() }));
  await renderMermaidIn(box);
  box.scrollTop = 0;
}

function showEditorView() {
  hideMdPreview();
  if (state.previewUrl) return;
  $("#monaco").style.display = "";
  state.editor?.layout?.();
}

function setMdViewMode(mode) {
  state.mdViewMode = mode === "preview" ? "preview" : "edit";
  localStorage.setItem("auc-md-view", state.mdViewMode);
  renderMdToolbar();
  if (!isMarkdownPath(state.activeTab)) return;
  if (state.mdViewMode === "preview") {
    const content = state.editor?.getValue() ?? state.fileCache[state.activeTab] ?? "";
    showMdPreviewView(content);
  } else {
    showEditorView();
  }
}

function renderMdToolbar() {
  const toolbar = $("#md-toolbar");
  if (!toolbar) return;
  if (!isMarkdownPath(state.activeTab)) {
    toolbar.classList.add("hidden");
    return;
  }
  toolbar.classList.remove("hidden");
  for (const btn of toolbar.querySelectorAll("[data-md-view]")) {
    btn.classList.toggle("active", btn.dataset.mdView === state.mdViewMode);
  }
}

function bindMdToolbar() {
  $("#md-toolbar")?.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-md-view]");
    if (!btn) return;
    setMdViewMode(btn.dataset.mdView);
  });
}

function showImagePreview(data) {
  hideMdPreview();
  const box = $("#image-preview");
  const url = `data:${data.mime_type};base64,${data.data_base64}`;
  box.innerHTML = `<img src="${url}" alt="${data.path}" />`;
  box.classList.remove("hidden");
  $("#monaco").style.display = "none";
}

function hideImagePreview() {
  $("#image-preview")?.classList.add("hidden");
  if (!(isMarkdownPath(state.activeTab) && state.mdViewMode === "preview")) {
    $("#monaco").style.display = "";
  }
}

function hideAppPreview() {
  state.previewUrl = null;
  state.previewTitle = "";
  $("#app-preview")?.classList.add("hidden");
  const frame = $("#preview-frame");
  if (frame) frame.src = "about:blank";
}

function showAppPreview(url, title = "预览") {
  hideImagePreview();
  hideMdPreview();
  state.editor?.dispose();
  state.editor = null;
  $("#monaco").style.display = "none";
  state.previewUrl = url;
  state.previewTitle = title;
  $("#preview-title").textContent = title;
  $("#preview-frame").src = url;
  $("#app-preview").classList.remove("hidden");
  $("#app").classList.add("has-editor");
  $("#editor-empty").style.display = "none";
}

function openHtmlPreview(path, title) {
  openProjectPreview({ kind: "html", preview_url: `/preview/${path}`, name: title || path });
}

function openProjectPreview(p) {
  const backend = state.projects.find(
    (x) => x.running && x.run_url && (x.kind === "python" || x.id === "backend"),
  );
  if (backend?.run_url && (p.kind === "html" || p.id === "frontend")) {
    showAppPreview(backend.run_url, p.name || backend.name);
    return;
  }
  if (p.preview_url) {
    showAppPreview(p.preview_url, p.name);
    return;
  }
  if (backend?.run_url) {
    showAppPreview(backend.run_url, p.name || backend.name);
    return;
  }
  alert("请先运行 backend 项目，再预览全栈应用。");
}

async function loadProjects() {
  const data = await api("/api/projects");
  state.projects = data.projects || [];
  const list = $("#project-list");
  if (!list) return;
  list.innerHTML = "";
  if (!state.projects.length) {
    list.innerHTML = '<div class="p-meta" style="padding:.35rem">未发现可运行项目<br>放入 index.html 或 package.json</div>';
    return;
  }
  for (const p of state.projects) {
    const card = document.createElement("div");
    card.className = "project-card";
    const runBadge = p.running ? '<span class="badge-run">运行中</span>' : "";
    card.innerHTML = `
      <div class="p-name">${p.name}${runBadge}</div>
      <div class="p-meta">${p.kind} · ${p.description || p.entry}</div>
      <div class="p-actions">
        <button type="button" class="btn primary sm" data-act="run">▶ 运行</button>
        ${p.preview_url ? '<button type="button" class="btn ghost sm" data-act="preview">预览</button>' : ""}
        ${p.running ? '<button type="button" class="btn ghost sm" data-act="stop">停止</button>' : ""}
      </div>`;
    card.querySelector('[data-act="run"]')?.addEventListener("click", () => runProject(p.id));
    card.querySelector('[data-act="preview"]')?.addEventListener("click", () => {
      openProjectPreview(p);
    });
    card.querySelector('[data-act="stop"]')?.addEventListener("click", () => stopProject(p));
    list.appendChild(card);
  }
}

function reloadPreviewAfterBackendStart(run) {
  if (!run || run.status !== "running" || !state.previewUrl) return;
  if (!state.previewUrl.startsWith("/preview/")) return;
  const frame = $("#preview-frame");
  if (!frame) return;
  const base = state.previewUrl.split("?")[0];
  frame.src = `${base}?auc=${run.run_id}&t=${Date.now()}`;
}

async function verifyProxyPreview(runId) {
  if (!runId || state.previewUrl !== `/proxy/${runId}/`) return;
  try {
    const res = await fetch(`/proxy/${runId}/`, { method: "GET" });
    if (res.status === 502 || res.status === 503 || res.status === 504) {
      alert("项目服务未响应，可能启动失败。请查看 logs/ 或停止后重新运行。");
    }
  } catch {
    alert("无法连接项目预览，请确认依赖已安装并重新运行。");
  }
}

async function runProject(projectId) {
  try {
    const run = await api("/api/projects/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId }),
    });
    state.activeRunId = run.run_id;
    const proj = state.projects.find((p) => p.id === projectId);
    if (run.status === "error") {
      alert(run.error || "启动失败");
      await loadProjects();
      return;
    }
    if (run.url) {
      const title = proj?.name || "项目";
      if (proj?.kind === "html" && run.url.startsWith("/preview/")) {
        openProjectPreview(proj);
      } else {
        showAppPreview(run.url, title);
        if (run.url.startsWith("/proxy/")) {
          setTimeout(() => verifyProxyPreview(run.run_id), 1200);
        }
      }
    }
    reloadPreviewAfterBackendStart(run);
    await loadProjects();
  } catch (e) {
    alert(e.message);
  }
}

async function stopProject(p) {
  await api("/api/projects/stop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: p.id, run_id: state.activeRunId }),
  });
  hideAppPreview();
  state.activeRunId = null;
  await loadProjects();
}

$("#projects-refresh")?.addEventListener("click", () => loadProjects());
$("#preview-stop")?.addEventListener("click", async () => {
  const running = state.projects.find((p) => p.running);
  if (running) await stopProject(running);
  else hideAppPreview();
});
$("#preview-newtab")?.addEventListener("click", () => {
  if (state.previewUrl) window.open(state.previewUrl, "_blank");
});

async function openFile(path) {
  const data = await api(`/api/workspace/file?path=${encodeURIComponent(path)}`);
  if (data.kind === "image") {
    if (!state.openTabs.includes(path)) state.openTabs.push(path);
    state.activeTab = path;
    renderTabs();
    renderMdToolbar();
    $("#app").classList.add("has-editor");
    hideMdPreview();
    hideImagePreview();
    state.editor?.dispose();
    state.editor = null;
    showImagePreview(data);
    loadTree(state.treePath);
    return;
  }
  hideAppPreview();
  hideImagePreview();
  if (!state.monacoReady) await initMonaco();
  if (!state.openTabs.includes(path)) state.openTabs.push(path);
  state.activeTab = path;
  renderTabs();
  $("#app").classList.add("has-editor");
  if (!state.editor) {
    state.editor = monaco.editor.create($("#monaco"), {
      value: data.content,
      language: monacoLang(path),
      theme: monacoThemeFor(state.colorTheme),
      fontSize: 13,
      minimap: { enabled: false },
      automaticLayout: true,
      scrollBeyondLastLine: false,
    });
    state.editor.onDidChangeModelContent(() => {
      if (state.activeTab) {
        state._dirty = state._dirty || {};
        state._dirty[state.activeTab] = true;
        state.fileCache[state.activeTab] = state.editor.getValue();
      }
    });
    state.editor.onDidChangeCursorSelection(() => updateContextBar());
  } else {
    const model = monaco.editor.createModel(data.content, monacoLang(path));
    state.editor.setModel(model);
  }
  state.fileCache[path] = data.content;
  if (state._dirty) state._dirty[path] = false;
  renderMdToolbar();
  if (isMarkdownPath(path) && state.mdViewMode === "preview") {
    await showMdPreviewView(data.content);
  } else {
    showEditorView();
  }
  updateContextBar();
  loadTree(state.treePath);
}

function getEditorContext() {
  const ctx = {
    auto_attach: state.autoAttach && state.mode === "code",
    include_file: true,
    active_file: null,
    file_content: "",
    selection: "",
    selection_start_line: null,
    selection_end_line: null,
    dirty: false,
    preview_url: state.previewUrl,
    preview_title: state.previewTitle,
    project_name: null,
    project_kind: null,
  };
  const running = state.projects.find((p) => p.running);
  if (running) {
    ctx.project_name = running.name;
    ctx.project_kind = running.kind;
  }
  if (state.activeTab && state.editor && $("#monaco")?.style.display !== "none") {
    ctx.active_file = state.activeTab;
    let content = state.editor.getValue();
    if (content.length > 24000) {
      content = content.slice(0, 24000) + "\n... (编辑器内容已截断)";
    }
    ctx.file_content = content;
    ctx.dirty = !!(state._dirty && state._dirty[state.activeTab]);
    const sel = state.editor.getSelection();
    const model = state.editor.getModel();
    if (sel && model && !sel.isEmpty()) {
      ctx.selection = model.getValueInRange(sel);
      ctx.selection_start_line = sel.startLineNumber;
      ctx.selection_end_line = sel.endLineNumber;
    }
  } else if (state.previewUrl) {
    ctx.active_file = state.previewTitle || null;
  }
  return ctx;
}

function updateContextBar() {
  const label = $("#ctx-label");
  const auto = $("#ctx-auto");
  if (!label) return;
  if (auto) auto.checked = state.autoAttach;
  const ctx = getEditorContext();
  if (ctx.selection) {
    label.textContent = `附带选中 · ${ctx.active_file || ""}`;
  } else if (ctx.active_file && state.autoAttach) {
    label.textContent = `附带 ${ctx.active_file.split("/").pop()}`;
  } else {
    label.textContent = "附带当前文件";
  }
}

async function syncActiveFileToServer() {
  if (!state.activeTab || !state.editor) return;
  const path = state.activeTab;
  const content = state.editor.getValue();
  if (!state._dirty?.[path] && state.fileCache[path] === content) return;
  await api("/api/workspace/file", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
  state.fileCache[path] = content;
  if (state._dirty) state._dirty[path] = false;
}

async function reloadOpenFile(path) {
  if (!path) return;
  const data = await api(`/api/workspace/file?path=${encodeURIComponent(path)}`);
  if (data.kind === "image") return;
  state.fileCache[path] = data.content;
  if (state._dirty) state._dirty[path] = false;
  if (state.activeTab === path && state.editor) {
    state.editor.setValue(data.content);
    if (isMarkdownPath(path) && state.mdViewMode === "preview") {
      await showMdPreviewView(data.content);
    }
  }
  if (state.previewUrl && state.previewUrl.includes(path)) {
    $("#preview-frame").src = state.previewUrl + "?t=" + Date.now();
  }
}

function layoutEditor() {
  state.editor?.layout();
}

function renderTabs() {
  const bar = $("#tab-bar-tabs");
  if (!bar) return;
  bar.innerHTML = "";
  for (const p of state.openTabs) {
    const tab = document.createElement("div");
    tab.className = "tab" + (p === state.activeTab ? " active" : "");
    const name = p.split("/").pop();
    tab.innerHTML = `<span>${name}</span><span class="tab-close">×</span>`;
    tab.querySelector(".tab-close").addEventListener("click", (ev) => {
      ev.stopPropagation();
      state.openTabs = state.openTabs.filter((t) => t !== p);
      if (state.activeTab === p) {
        state.activeTab = state.openTabs[0] || null;
        if (state.activeTab) openFile(state.activeTab);
        else {
          $("#app").classList.remove("has-editor");
          hideImagePreview();
          hideAppPreview();
          hideMdPreview();
          state.editor?.dispose();
          state.editor = null;
        }
      }
      renderTabs();
    });
    tab.addEventListener("click", () => openFile(p));
    bar.appendChild(tab);
  }
}

// ── 聊天流式 ──
function targetMessages() {
  return state.mode === "chat" ? $("#chat-messages") : $("#agent-messages");
}

function buildUserMessageEl(text, images = []) {
  const el = document.createElement("div");
  el.className = "msg msg-user";
  if (text) {
    const t = document.createElement("div");
    t.textContent = text;
    el.appendChild(t);
  }
  if (images?.length) {
    const wrap = document.createElement("div");
    wrap.className = "msg-images";
    for (const img of images) {
      const im = document.createElement("img");
      im.src = `data:${img.mime_type};base64,${img.data_base64}`;
      im.alt = img.name || "image";
      wrap.appendChild(im);
    }
    el.appendChild(wrap);
  }
  return el;
}

function appendUser(text, images = []) {
  targetMessages().appendChild(buildUserMessageEl(text, images));
  scrollMessages();
}

function formatConvTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) {
      return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
  } catch {
    return "";
  }
}

async function renderChatHistory(messages) {
  const panels = ["#chat-messages", "#agent-messages"];
  for (const sel of panels) {
    const root = $(sel);
    if (root) root.innerHTML = "";
  }
  for (const m of messages || []) {
    if (m.role === "user") {
      const el = buildUserMessageEl(m.content, m.images);
      for (const sel of panels) $(sel)?.appendChild(el.cloneNode(true));
    } else if (m.role === "assistant" && m.content) {
      for (const sel of panels) {
        const root = $(sel);
        if (!root) continue;
        const el = document.createElement("div");
        el.className = "msg msg-assistant";
        const stream = document.createElement("span");
        stream.className = "msg-stream";
        stream.appendChild(buildMessageContent(m.content, { theme: messageTheme() }));
        el.innerHTML = '<span class="marker">◆</span>';
        el.appendChild(stream);
        root.appendChild(el);
        await renderMermaidIn(stream);
      }
    } else if (m.role === "tool") {
      for (const sel of panels) {
        const root = $(sel);
        if (!root) continue;
        const el = document.createElement("div");
        el.className = "msg msg-tool";
        el.innerHTML = `<div>● ${escapeHtml(m.name || "tool")}</div>`;
        if (m.content) {
          const r = document.createElement("div");
          r.className = "result";
          r.textContent = (m.is_error ? "✗ " : "⎿ ") + m.content;
          el.appendChild(r);
        }
        root.appendChild(el);
      }
    }
  }
  if (state.info?.release) renderUpdateNotices(state.info.release);
  scrollMessages();
}

async function loadConversations() {
  try {
    const data = await api("/api/chat/conversations");
    state.conversations = data.conversations || [];
    state.activeConversationId = data.active_id || state.activeConversationId;
    renderConversationList();
  } catch { /* ignore */ }
}

function renderConversationList() {
  const list = $("#conversation-list");
  if (!list) return;
  list.innerHTML = "";
  if (!state.conversations.length) {
    list.innerHTML = '<div class="conv-empty">暂无记录，发送消息开始对话</div>';
    return;
  }
  for (const c of state.conversations) {
    const row = document.createElement("div");
    row.className = "conv-item" + (c.id === state.activeConversationId ? " active" : "");
    row.dataset.id = c.id;
    const meta = `${formatConvTime(c.updated_at)} · ${c.message_count || 0} 轮`;
    row.innerHTML = `
      <div class="conv-body">
        <div class="conv-title">${escapeHtml(c.title || "新对话")}</div>
        <div class="conv-meta">${escapeHtml(meta)}</div>
      </div>
      <button type="button" class="conv-del" title="删除">${icon("trash", { size: 14 })}</button>`;
    row.addEventListener("click", () => switchConversation(c.id));
    row.querySelector(".conv-del").addEventListener("click", (ev) => {
      ev.stopPropagation();
      deleteConversation(c.id);
    });
    list.appendChild(row);
  }
}

async function switchConversation(convId) {
  if (state.streaming || convId === state.activeConversationId) return;
  const data = await api(`/api/chat/conversations/${convId}/switch`, { method: "POST" });
  state.activeConversationId = data.conversation_id;
  await renderChatHistory(data.messages || []);
  await loadConversations();
  await refreshAgentStats();
}

async function newConversation() {
  if (state.streaming) return;
  const data = await api("/api/chat/conversations", { method: "POST" });
  state.activeConversationId = data.conversation_id;
  await renderChatHistory([]);
  await loadConversations();
  await refreshAgentStats();
}

async function deleteConversation(convId) {
  if (state.streaming) return;
  const data = await api(`/api/chat/conversations/${convId}`, { method: "DELETE" });
  if (data.active_id) state.activeConversationId = data.active_id;
  if (data.messages !== undefined) await renderChatHistory(data.messages);
  await loadConversations();
  await refreshAgentStats();
}

function scrollMessages() {
  const c = targetMessages();
  if (state.mode === "chat") {
    const scroller = $(".chat-scroll");
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
    return;
  }
  c.scrollTop = c.scrollHeight;
}

let streamEl = null;
let streamText = "";
let renderTimer = null;
const diagramRepairMeta = new WeakMap();

function messageTheme() {
  return isColorThemeDark(state.colorTheme) ? "dark" : "light";
}

function beginAssistant() {
  streamText = "";
  streamEl = document.createElement("div");
  streamEl.className = "msg msg-assistant";
  streamEl.innerHTML = '<span class="marker">◆</span><span class="msg-stream"></span>';
  targetMessages().appendChild(streamEl);
}

function paintAssistantMessage(msgEl, text) {
  const stream = msgEl.querySelector(".msg-stream");
  if (!stream) return Promise.resolve([]);
  stream.replaceChildren(buildMessageContent(text, { theme: messageTheme() }));
  return renderMermaidIn(stream);
}

async function repairDiagramsInMessage(msgEl, text) {
  const meta = diagramRepairMeta.get(msgEl) || { attempts: 0, repairing: false };
  if (meta.repairing) return text;
  let currentText = text;
  let failures = await paintAssistantMessage(msgEl, currentText);
  let attempts = meta.attempts || 0;

  while (failures.length && attempts < 2 && !state.streaming) {
    attempts += 1;
    diagramRepairMeta.set(msgEl, { repairing: true, attempts });
    const fail = failures[0];
    const blocks = msgEl.querySelectorAll(".diagram-error");
    blocks.forEach((b) => b.classList.add("diagram-repairing"));

    try {
      const res = await fetch("/api/chat/diagram-fix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: fail.code,
          error: fail.error,
          force_agent: attempts > 1,
        }),
      });
      if (!res.ok) break;
      const data = await res.json();
      if (!data.changed || !data.code || data.code.trim() === fail.code.trim()) break;

      currentText = replaceMermaidInText(currentText, fail.code, data.code);
      msgEl.dataset.msgText = currentText;
      failures = await paintAssistantMessage(msgEl, currentText);
      if (!failures.length) {
        const note = document.createElement("div");
        note.className = "msg msg-note diagram-fixed-note";
        note.textContent =
          data.method === "agent" ? "› 智能体已修复图表语法" : "› 已自动修复图表语法";
        msgEl.insertAdjacentElement("afterend", note);
      }
    } catch {
      break;
    } finally {
      diagramRepairMeta.set(msgEl, { repairing: false, attempts });
    }
  }
  scrollMessages();
  return currentText;
}

function flushMessageRender() {
  if (!streamEl) return;
  streamEl.dataset.msgText = streamText;
  paintAssistantMessage(streamEl, streamText)
    .then((failures) => {
      if (!state.streaming && failures.length && streamEl) {
        repairDiagramsInMessage(streamEl, streamText);
      }
      scrollMessages();
    })
    .catch(() => scrollMessages());
}

function scheduleMessageRender() {
  clearTimeout(renderTimer);
  renderTimer = setTimeout(flushMessageRender, 100);
}

function appendDelta(delta) {
  if (!streamEl) beginAssistant();
  streamText += delta;
  scheduleMessageRender();
}

function appendTool(name, args, summary, isError) {
  const el = document.createElement("div");
  el.className = "msg msg-tool";
  const label = formatTool(name, args);
  el.innerHTML = `<div>● ${label}</div>`;
  if (summary) {
    const r = document.createElement("div");
    r.className = "result";
    r.textContent = (isError ? "✗ " : "⎿ ") + summary;
    el.appendChild(r);
  }
  targetMessages().appendChild(el);
  if (name === "write_file" && args?.path) {
    loadTree(state.treePath);
    loadProjects();
    reloadOpenFile(args.path).catch(() => {
      if (state.mode === "code") openFile(args.path).catch(() => {});
    });
  }
  scrollMessages();
}

function formatTool(name, args = {}) {
  if (name === "write_file") return `Write(${args.path || "?"})`;
  if (name === "read_file") return `Read(${args.path || "?"})`;
  if (name === "delete_path") return `Delete(${args.path || "?"})`;
  if (name === "list_dir") return `List(${args.path || "."})`;
  if (name === "fetch_url") return `Fetch(${args.url || "?"})`;
  return name;
}

// 授权请求队列：同一步可能并行产生多个 L3 请求，逐个弹卡，避免覆盖丢单
let approvalQueue = [];
let pendingApprovalId = null;

function hideApprovalDialog() {
  pendingApprovalId = null;
  const overlay = $("#approval-overlay");
  if (overlay) overlay.classList.add("hidden");
}

function enqueueApproval(payload = {}) {
  const rid = payload.request_id;
  if (!rid) return;
  if (pendingApprovalId === rid || approvalQueue.some((p) => p.request_id === rid)) {
    return;
  }
  approvalQueue.push(payload);
  if (!pendingApprovalId) showNextApproval();
}

function showNextApproval() {
  const payload = approvalQueue.shift();
  if (!payload) return;
  pendingApprovalId = payload.request_id;
  const overlay = $("#approval-overlay");
  const summary = $("#approval-summary");
  const urlEl = $("#approval-url");
  if (!overlay) return;
  const extra = approvalQueue.length ? `（还有 ${approvalQueue.length} 个待批）` : "";
  if (summary) {
    summary.textContent =
      (payload.risk_summary || `智能体请求执行：${payload.tool || "L3"}`) + extra;
  }
  if (urlEl) {
    const args = payload.arguments || {};
    const url = args.url || args.command || args.path || "";
    const save = args.save_path || "";
    urlEl.textContent = url + (save ? `\n保存到: ${save}` : "");
  }
  overlay.classList.remove("hidden");
}

async function submitApproval(approved) {
  if (!pendingApprovalId) return;
  const id = pendingApprovalId;
  hideApprovalDialog();
  try {
    await api("/api/chat/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request_id: id,
        approved,
        reason: approved ? "" : "用户拒绝",
      }),
    });
    appendNotes([approved ? "› 已授权" : "› 已拒绝"]);
  } catch (e) {
    appendNotes(["✗ 授权失败: " + e.message]);
  }
  // 队列里还有未决请求则继续弹卡
  showNextApproval();
}

async function recoverPendingApprovals() {
  try {
    const data = await api("/api/chat/approvals");
    for (const p of data.pending || []) enqueueApproval(p);
  } catch {
    /* 接口不可用时静默 */
  }
}

function appendNotes(notes) {
  for (const n of notes) {
    const el = document.createElement("div");
    el.className = "msg msg-note";
    el.textContent = "› " + n;
    targetMessages().appendChild(el);
  }
}

function chatHasInput(text, images, channel) {
  if ((text && text.trim()) || images.length) return true;
  if (channel !== "agent") return false;
  const ctx = getEditorContext();
  if (ctx.selection && ctx.selection.trim()) return true;
  if (ctx.auto_attach && ctx.active_file) return true;
  return false;
}

async function sendMessage(text, channel = "agent") {
  const images = [...(state.attachments[channel] || [])];
  if (!chatHasInput(text, images, channel)) return;
  if (state.streaming) return;
  const streamConversationId = state.activeConversationId;
  state.streaming = true;
  setButtons(true);
  renderAgentProfile();
  const payloadImages = images.map(({ mime_type, data_base64, name }) => ({
    mime_type, data_base64, name,
  }));
  appendUser(text, payloadImages);
  state.attachments[channel] = [];
  renderAttachStrip(channel);

  const controller = new AbortController();
  state.abort = controller;

  try {
    if (channel === "agent") {
      try {
        await syncActiveFileToServer();
      } catch (syncErr) {
        appendNotes([`保存跳过: ${syncErr.message}`]);
      }
    }
    const context = channel === "agent" ? getEditorContext() : null;
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text || "",
        images: payloadImages,
        context,
        work_mode: state.workMode,
        role_id: state.roleId,
        conversation_id: streamConversationId,
      }),
      signal: controller.signal,
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const errBody = await res.json();
        detail = errBody.detail || errBody.message || JSON.stringify(errBody);
        if (Array.isArray(detail)) detail = detail.map((d) => d.msg || d).join("; ");
      } catch {
        try { detail = await res.text(); } catch { /* ignore */ }
      }
      throw new Error(detail);
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    streamEl = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() || "";
      for (const chunk of parts) {
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const ev = JSON.parse(line.slice(6));
        if (
          streamConversationId &&
          state.activeConversationId &&
          streamConversationId !== state.activeConversationId
        ) {
          continue;
        }
        handleEvent(ev, streamConversationId);
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") {
      const el = document.createElement("div");
      el.className = "msg msg-note";
      el.textContent = "✗ " + e.message;
      targetMessages().appendChild(el);
    }
  } finally {
    clearTimeout(renderTimer);
    const staleStream = streamConversationId !== state.activeConversationId;
    if (!staleStream) {
      const doneEl = streamEl;
      const doneText = streamText;
      if (doneEl && doneText) {
        doneEl.dataset.msgText = doneText;
        paintAssistantMessage(doneEl, doneText)
          .then((failures) => {
            if (failures.length) return repairDiagramsInMessage(doneEl, doneText);
            return doneText;
          })
          .finally(() => scrollMessages());
      }
    } else {
      try {
        const data = await api(`/api/chat/conversations/${state.activeConversationId}`);
        await renderChatHistory(data.messages || []);
      } catch { /* ignore */ }
    }
    state.streaming = false;
    state.abort = null;
    streamEl = null;
    streamText = "";
    setButtons(false);
    refreshAgentStats();
    loadConversations();
  }
}

function handleEvent(ev, streamConversationId = null) {
  if (ev.type === "error") {
    const code = ev.payload?.code;
    if (code === "conversation_mismatch") {
      loadConversations();
    }
    const el = document.createElement("div");
    el.className = "msg msg-note";
    el.textContent = "✗ " + (ev.payload?.message || "未知错误");
    targetMessages().appendChild(el);
    return;
  }
  if (ev.type === "note") {
    appendNotes(ev.payload?.notes || []);
    return;
  }
  if (ev.type === "approval_required") {
    enqueueApproval(ev.payload || {});
    return;
  }
  if (ev.type === "run_start") {
    beginAssistant();
    return;
  }
  if (ev.type === "model_delta") {
    if (ev.payload?.delta) appendDelta(ev.payload.delta);
    return;
  }
  if (ev.type === "done") {
    clearTimeout(renderTimer);
    if (streamEl && streamText) flushMessageRender();
    if (ev.payload?.status !== "completed" && ev.payload?.error) {
      const el = document.createElement("div");
      el.className = "msg msg-note";
      el.textContent = "✗ " + ev.payload.error;
      targetMessages().appendChild(el);
    } else if (ev.payload?.status === "completed" && !streamText && !streamEl) {
      const out = ev.payload?.output;
      if (out) appendDelta(out);
    }
    return;
  }
  if (ev.type === "tool_start") {
    clearTimeout(renderTimer);
    if (streamEl && streamText) flushMessageRender();
    streamEl = null;
    state._pendingTool = {
      name: ev.payload?.tool,
      args: ev.payload?.arguments || {},
    };
    return;
  }
  if (ev.type === "tool_end") {
    const pending = state._pendingTool || {};
    const toolName = ev.payload?.tool || pending.name;
    appendTool(
      toolName,
      pending.args || {},
      ev.payload?.summary,
      ev.payload?.is_error,
    );
    state._pendingTool = null;
    if (
      !ev.payload?.is_error
      && ["define_role", "update_role", "switch_role"].includes(toolName)
    ) {
      loadInfo()
        .then(() => {
          populateRoleSelects();
          bindRoleSelects();
          renderAgentProfile();
        })
        .catch(() => {});
    }
    return;
  }
  if (ev.type === "run_end" && ev.payload?.status === "cancelled") {
    const el = document.createElement("div");
    el.className = "msg msg-note";
    el.textContent = "⊘ 已取消";
    targetMessages().appendChild(el);
  }
}

function setButtons(busy) {
  ["#btn-send", "#btn-send-chat"].forEach((s) => {
    const b = $(s);
    if (b) b.disabled = busy;
  });
  ["#btn-cancel", "#btn-cancel-chat"].forEach((s) => {
    const b = $(s);
    if (b) b.disabled = !busy;
  });
}

function renderAttachStrip(channel) {
  const strip = $(channel === "chat" ? "#attach-strip-chat" : "#attach-strip-agent");
  if (!strip) return;
  strip.innerHTML = "";
  for (let i = 0; i < state.attachments[channel].length; i++) {
    const img = state.attachments[channel][i];
    const thumb = document.createElement("div");
    thumb.className = "attach-thumb";
    thumb.innerHTML = `<img src="data:${img.mime_type};base64,${img.data_base64}" alt="" /><button type="button">×</button>`;
    thumb.querySelector("button").addEventListener("click", () => {
      state.attachments[channel].splice(i, 1);
      renderAttachStrip(channel);
    });
    strip.appendChild(thumb);
  }
}

async function addImageFiles(files, channel) {
  for (const file of files) {
    if (!file.type.startsWith("image/")) continue;
    if (file.size > 20 * 1024 * 1024) {
      alert(`图片过大: ${file.name}`);
      continue;
    }
    const b64 = await new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(String(r.result).split(",")[1]);
      r.onerror = rej;
      r.readAsDataURL(file);
    });
    state.attachments[channel].push({
      mime_type: file.type,
      data_base64: b64,
      name: file.name,
    });
  }
  renderAttachStrip(channel);
}

function bindComposer(formSel, inputSel, sendSel, cancelSel, channel, fileSel, attachBtnSel) {
  const form = $(formSel);
  const input = $(inputSel);
  if (!input) return;
  const submit = (ev) => {
    ev?.preventDefault();
    const t = input.value.trim();
    const canCtx = channel === "agent" && state.autoAttach && getEditorContext().active_file;
    if (!t && !state.attachments[channel].length && !canCtx) return;
    input.value = "";
    sendMessage(t, channel);
  };
  if (form) form.addEventListener("submit", submit);
  if ($(sendSel)) $(sendSel).addEventListener("click", submit);
  if ($(cancelSel)) {
    $(cancelSel).addEventListener("click", async () => {
      state.abort?.abort();
      await api("/api/chat/cancel", { method: "POST" });
    });
  }
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      submit(ev);
    }
  });
  input.addEventListener("paste", (ev) => {
    const items = ev.clipboardData?.items || [];
    const imgs = [];
    for (const it of items) {
      if (it.type.startsWith("image/")) imgs.push(it.getAsFile());
    }
    if (imgs.length) {
      ev.preventDefault();
      addImageFiles(imgs.filter(Boolean), channel);
    }
  });
  const fileInput = $(fileSel);
  const attachBtn = $(attachBtnSel);
  if (attachBtn && fileInput) {
    attachBtn.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
      addImageFiles([...fileInput.files], channel);
      fileInput.value = "";
    });
  }
}

bindComposer("#composer", "#prompt", "#btn-send", "#btn-cancel", "agent", "#file-agent", "#btn-attach-agent");
bindComposer(null, "#prompt-chat", "#btn-send-chat", "#btn-cancel-chat", "chat", "#file-chat", "#btn-attach-chat");

$("#ctx-auto")?.addEventListener("change", (ev) => {
  state.autoAttach = ev.target.checked;
  localStorage.setItem("auc-auto-attach", state.autoAttach ? "1" : "0");
  updateContextBar();
});
$("#btn-insert-file")?.addEventListener("click", () => {
  const input = $("#prompt");
  if (!input) return;
  input.value = (input.value ? input.value + " " : "") + "@当前文件 ";
  input.focus();
});
$("#btn-insert-sel")?.addEventListener("click", () => {
  const input = $("#prompt");
  if (!input) return;
  input.value = (input.value ? input.value + " " : "") + "@选中 ";
  input.focus();
});

async function clearChat() {
  await newConversation();
}
$("#chat-clear")?.addEventListener("click", clearChat);
$("#btn-clear-chat")?.addEventListener("click", clearChat);
$("#conv-new")?.addEventListener("click", () => newConversation().catch(() => {}));
$("#approval-allow")?.addEventListener("click", () => submitApproval(true));
$("#approval-deny")?.addEventListener("click", () => submitApproval(false));

// ── 启动 ──
async function boot() {
  initThemes();
  initSidebarChrome();
  initTerminalPanel();
  bindUpdateBanner();
  bindModelSettings();
  window.addEventListener("auc-terminal-resize", layoutEditor);
  setMode(state.mode);
  bindMdToolbar();
  await loadInfo();
  await loadTree(".");
  await loadProjects();
  initMonaco().catch(() => {});
  updateContextBar();
  // 找回刷新/覆盖导致丢失的授权卡片，并周期兜底（run 挂起等待授权时可恢复）
  recoverPendingApprovals();
  setInterval(recoverPendingApprovals, 15000);
}

boot().catch((e) => {
  document.body.innerHTML = `<pre style="padding:2rem;color:#c00">启动失败: ${e.message}</pre>`;
});
