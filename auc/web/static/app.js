/** AuC Web — Code (JupyterLab) + Chat (简约) 双模式 */

import {
  buildMessageContent,
  renderMermaidIn,
  replaceMermaidInText,
  richRenderersReady,
} from "./message_render.js?v=48";
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
import {
  hideDocumentPreview,
  showDocumentPreview,
} from "./document_panel.js";
import { applyI18n, getLocale, t, toggleLocale } from "./i18n.js";

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
  approvalMode: localStorage.getItem("auc-approval-mode") || "ask-on-state",
  approvalModes: [],
  autoApproveAvailable: true,
  workModes: [],
  roleId: localStorage.getItem("auc-role") || "auto",
  roles: [],
  roleDivisions: [],
  skills: [],
  skillMode: localStorage.getItem("auc-skill-mode") || "auto",
  skillPinned: JSON.parse(localStorage.getItem("auc-skill-pinned") || "[]"),
  activeConversationId: null,
  conversations: [],
  turns: [],
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
      toggle.title = open ? t("sidebar.fold") : t("sidebar.unfold");
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

// ── API 接口 ──
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || res.statusText);
  }
  return res.json();
}

function currentRoleSpec() {
  if (state.roleId === "auto") {
    return state.roles.find((r) => r.auto || r.id === "auto") || {
      id: "auto",
      label: t("plaza.roleAuto"),
      description: t("plaza.roleAutoDesc"),
      capabilities: [t("plaza.roleAuto")],
    };
  }
  return state.roles.find((r) => r.id === state.roleId) || state.roles[0] || null;
}

function roleLabel(id) {
  if (id === "auto") return t("plaza.roleAuto");
  const r = state.roles.find((x) => x.id === id);
  return r ? r.label : id;
}

function renderChoicePill(el, kind, value) {
  if (!el) return;
  const labelKey =
    kind === "role" ? "header.roleKind" : kind === "skill" ? "header.skillKind" : "header.modelKind";
  const safe = escapeHtml(value || "");
  const titleKey =
    kind === "role" ? "plaza.roleOpen" : kind === "skill" ? "plaza.skillOpen" : "plaza.modelOpen";
  el.setAttribute("role", "button");
  el.setAttribute("tabindex", "0");
  el.setAttribute("aria-label", `${t(labelKey)}: ${value || ""}`);
  el.title = t(titleKey);
  el.innerHTML =
    `<span class="choice-pill-kind">${escapeHtml(t(labelKey))}</span>` +
    `<span class="choice-pill-value"${safe ? ` title="${safe}"` : ""}>${safe}</span>`;
}

function roleHeaderValue() {
  const spec = currentRoleSpec();
  const label = roleLabel(state.roleId);
  const div =
    state.roleId !== "auto" && spec?.division && spec.division !== "__auto__"
      ? divisionLabel(spec.division)
      : "";
  return div && state.roleId !== "auto" ? `${div} · ${label}` : label;
}

function skillHeaderValue() {
  if (state.skillMode === "manual") {
    if (!state.skillPinned.length) return t("plaza.skillManual");
    if (state.skillPinned.length === 1) return state.skillPinned[0];
    return state.skillPinned.join(", ");
  }
  return t("plaza.skillAuto");
}

function modelHeaderValue(model) {
  const provider = state.info?.model?.provider;
  const mid = model || state.info?.model?.model || "";
  return provider ? `${provider} / ${mid}` : mid;
}

function updateModelPillDisplay(model) {
  const pill = $("#model-pill");
  if (!pill) return;
  const value = modelHeaderValue(model);
  if (!value) return;
  renderChoicePill(pill, "model", value);
  if (model && state.info?.model) state.info.model.model = model;
}

function updateRoleTriggers() {
  const spec = currentRoleSpec();
  const label = roleLabel(state.roleId);
  const detail = spec?.vibe || spec?.title || spec?.description || "";
  const tip = [detail, spec?.when_to_use].filter(Boolean).join(" — ") || label;
  syncRoleTreeTriggers(label, tip);
  renderChoicePill($("#role-pill"), "role", roleHeaderValue());
  updateSkillTriggers();
}

function rolesForTree() {
  return state.roles.length
    ? state.roles
    : [
        { id: "auto", label: t("plaza.roleAuto"), auto: true },
        { id: "coder", label: t("role.coder") },
      ];
}

function groupRolesForTree() {
  const roles = rolesForTree();
  const groups = new Map();
  let autoRole = null;
  for (const r of roles) {
    if (r.auto || r.id === "auto") {
      autoRole = r;
      continue;
    }
    const div = r.division || "custom";
    if (!groups.has(div)) groups.set(div, []);
    groups.get(div).push(r);
  }
  const order = state.roleDivisions.length
    ? state.roleDivisions.map((d) => d.id)
    : ["specialized", "engineering", "operations", "education", "custom"];
  return { autoRole, groups, order };
}

function renderRoleTreeMenu(menuEl, activeRoleId = state.roleId) {
  if (!menuEl) return;
  const { autoRole, groups, order } = groupRolesForTree();
  const parts = [];
  if (autoRole) {
    parts.push(
      `<button type="button" class="role-tree-item auto${activeRoleId === "auto" ? " active" : ""}" data-role-id="auto">${escapeHtml(autoRole.label || t("plaza.roleAuto"))}</button>`
    );
  }
  for (const divId of order) {
    const items = groups.get(divId);
    if (!items?.length) continue;
    parts.push(
      `<div class="role-tree-group is-open" data-division="${escapeHtml(divId)}">` +
        `<button type="button" class="role-tree-group-head">` +
        `<span class="role-tree-toggle" aria-hidden="true">▶</span>` +
        `<span class="role-tree-group-label">${escapeHtml(divisionLabel(divId))}</span>` +
        `<span class="facet-chip-badge">${items.length}</span>` +
        `</button>` +
        `<div class="role-tree-children">` +
        items
          .map(
            (r) =>
              `<button type="button" class="role-tree-item${r.id === activeRoleId ? " active" : ""}" data-role-id="${escapeHtml(r.id)}">${escapeHtml(r.label)}</button>`
          )
          .join("") +
        `</div></div>`
    );
  }
  menuEl.innerHTML = parts.join("");
}

const ROLE_TREE_IDS = ["#role-tree-chat", "#role-tree-agent", "#role-tree-retry"];

function activeRoleIdForTreeWrap(wrap) {
  if (wrap?.dataset.roleTreeContext === "retry") return _retryRoleId || state.roleId;
  return state.roleId;
}

function renderRoleTreeMenus() {
  for (const id of ROLE_TREE_IDS) {
    const wrap = $(id);
    if (!wrap) continue;
    const activeId = activeRoleIdForTreeWrap(wrap);
    renderRoleTreeMenu(roleTreeMenuEl(wrap), activeId);
    const labelEl = wrap.querySelector(".role-tree-trigger-label");
    if (labelEl) labelEl.textContent = roleLabel(activeId);
  }
}

function syncRoleTreeTriggers(label, tip) {
  for (const id of ["#role-tree-chat", "#role-tree-agent"]) {
    const wrap = $(id);
    const trigger = wrap?.querySelector(".role-tree-trigger");
    const labelEl = wrap?.querySelector(".role-tree-trigger-label");
    if (labelEl) labelEl.textContent = label;
    if (trigger) trigger.title = tip || label;
  }
}

function roleTreeMenuEl(wrap) {
  return wrap?._roleTreeMenu || wrap?.querySelector(".role-tree-menu");
}

function roleTreePortalRoot() {
  return document.getElementById("app") || document.body;
}

function positionRoleTreeMenu(wrap) {
  const menu = roleTreeMenuEl(wrap);
  const trigger = wrap?.querySelector(".role-tree-trigger");
  if (!menu || !trigger) return;
  if (!wrap._roleTreeMenu) wrap._roleTreeMenu = menu;
  const portal = roleTreePortalRoot();
  if (menu.parentElement !== portal) {
    wrap._roleTreeMenuHome = wrap;
    portal.appendChild(menu);
  }
  menu.classList.add("role-tree-menu--floating");
  const rect = trigger.getBoundingClientRect();
  const gap = 6;
  menu.style.minWidth = `${Math.max(rect.width, 220)}px`;
  let left = rect.left;
  const menuW = menu.offsetWidth;
  if (left + menuW > window.innerWidth - 8) left = window.innerWidth - menuW - 8;
  left = Math.max(8, left);
  const menuH = menu.offsetHeight;
  let top = rect.bottom + gap;
  if (top + menuH > window.innerHeight - 8 && rect.top > menuH + gap) {
    top = rect.top - menuH - gap;
  }
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
}

function dockRoleTreeMenu(wrap) {
  const menu = wrap?._roleTreeMenu;
  if (!menu) return;
  menu.classList.remove("role-tree-menu--floating");
  menu.style.left = "";
  menu.style.top = "";
  menu.style.minWidth = "";
  const home = wrap._roleTreeMenuHome || wrap;
  const portal = roleTreePortalRoot();
  if ((menu.parentElement === portal || menu.parentElement === document.body) && home) {
    home.appendChild(menu);
  }
}

function repositionOpenRoleTreeMenus() {
  document.querySelectorAll(".role-tree-select").forEach((wrap) => {
    const menu = roleTreeMenuEl(wrap);
    if (menu && !menu.classList.contains("hidden")) {
      positionRoleTreeMenu(wrap);
    }
  });
}

function closeRoleTreeMenus(exceptWrap = null) {
  document.querySelectorAll(".role-tree-select").forEach((wrap) => {
    if (exceptWrap && wrap === exceptWrap) return;
    const menu = roleTreeMenuEl(wrap);
    menu?.classList.add("hidden");
    dockRoleTreeMenu(wrap);
    const trigger = wrap.querySelector(".role-tree-trigger");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
  });
}

function toggleRoleTreeMenu(wrap) {
  const menu = roleTreeMenuEl(wrap);
  const trigger = wrap.querySelector(".role-tree-trigger");
  if (!menu || !trigger) return;
  if (!wrap._roleTreeMenu) wrap._roleTreeMenu = menu;
  const willOpen = menu.classList.contains("hidden");
  closeRoleTreeMenus();
  if (willOpen) {
    renderRoleTreeMenu(menu, activeRoleIdForTreeWrap(wrap));
    menu.classList.remove("hidden");
    positionRoleTreeMenu(wrap);
    trigger.setAttribute("aria-expanded", "true");
  }
}

async function selectRoleFromTree(roleId, wrap) {
  if (wrap?.dataset.roleTreeContext === "retry") {
    _retryRoleId = roleId || "auto";
    renderRoleTreeMenus();
    closeRoleTreeMenus();
    return;
  }
  setRole(roleId);
  if (roleId !== "auto") {
    try {
      await api(
        `/api/roles/${encodeURIComponent(roleId)}/activate?locale=${encodeURIComponent(getLocale())}`,
        { method: "POST" }
      );
    } catch {
      /* 激活失败不阻断选用 */
    }
  }
  closeRoleTreeMenus();
  renderRoleTreeMenus();
}

function bindRoleTreeSelects() {
  document.querySelectorAll(".role-tree-select").forEach((wrap) => {
    if (wrap.dataset.bound) return;
    wrap.dataset.bound = "1";
    const trigger = wrap.querySelector(".role-tree-trigger");
    const menu = wrap.querySelector(".role-tree-menu");
    if (menu) wrap._roleTreeMenu = menu;
    trigger?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      toggleRoleTreeMenu(wrap);
    });
    menu?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const groupHead = ev.target.closest(".role-tree-group-head");
      if (groupHead) {
        groupHead.closest(".role-tree-group")?.classList.toggle("is-open");
        return;
      }
      const item = ev.target.closest(".role-tree-item[data-role-id]");
      if (item) void selectRoleFromTree(item.dataset.roleId || "auto", wrap);
    });
  });
  if (!document.body.dataset.roleTreeBound) {
    document.body.dataset.roleTreeBound = "1";
    document.addEventListener("click", () => closeRoleTreeMenus());
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") closeRoleTreeMenus();
    });
    window.addEventListener("resize", repositionOpenRoleTreeMenus);
    window.addEventListener("scroll", repositionOpenRoleTreeMenus, true);
  }
}

// 智能体运行状态：Code（agent-panel 头）与 Chat（chat-header）两个界面同步显示。
function updateAgentStatus(info = state.info) {
  const els = document.querySelectorAll(".agent-status");
  if (!els.length) return;
  let text;
  let cls;
  if (state.streaming) {
    text = t("agent.thinking");
    cls = "agent-status busy";
  } else {
    text = (info?.turns || 0) > 0 ? t("agent.online") : t("agent.ready");
    cls = "agent-status";
  }
  for (const el of els) {
    el.textContent = text;
    el.className = cls;
  }
}

function renderAgentProfile(info = state.info) {
  if (!info) return;
  const agent = info.agent || {};
  const role = currentRoleSpec();
  const profile = $("#agent-profile");
  const title = $("#agent-title");
  const desc = $("#agent-desc");
  const meta = $("#agent-meta");
  const tags = $("#agent-tags");
  if (!title) return;

  const turns = info.turns || 0;
  if (profile) profile.classList.toggle("compact", turns > 0);

  title.textContent = role?.label || agent.name || t("agent.defaultTitle");
  if (desc) {
    desc.textContent =
      role?.description || agent.description || agent.title || t("agent.defaultDesc");
  }
  updateAgentStatus(info);
  if (meta) {
    meta.hidden = true;
    meta.innerHTML = "";
  }
  if (tags) {
    tags.hidden = true;
    tags.innerHTML = "";
  }
  renderActiveConversationUsage(info.conversation?.usage);
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
    : [{ id: "auto", label: t("workmode.auto"), description: "" }];
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

function populateApprovalSelects() {
  const modes = state.approvalModes.length
    ? state.approvalModes
    : [
        { id: "ask-every-write", label: t("approval.mode.ask-every-write"), hint: "" },
        { id: "ask-on-state", label: t("approval.mode.ask-on-state"), hint: "" },
        { id: "ask-on-danger", label: t("approval.mode.ask-on-danger"), hint: "" },
      ];
  for (const sel of ["#approval-mode-select", "#approval-mode-agent"]) {
    const el = $(sel);
    if (!el) continue;
    const prev = el.value || state.approvalMode;
    el.innerHTML = modes
      .map((m) => {
        const disabled =
          m.id === "auto-approve" && state.autoApproveAvailable === false ? " disabled" : "";
        return `<option value="${escapeHtml(m.id)}" title="${escapeHtml(m.hint || "")}"${disabled}>${escapeHtml(m.label)}</option>`;
      })
      .join("");
    const pick = modes.some((m) => m.id === prev && !(m.id === "auto-approve" && !state.autoApproveAvailable))
      ? prev
      : "ask-on-state";
    el.value = pick;
  }
  setApprovalMode($("#approval-mode-select")?.value || state.approvalMode, { persist: false, save: false });
}

async function saveApprovalModeToServer(mode) {
  try {
    await api("/api/settings/approval", {
      method: "PUT",
      body: JSON.stringify({ mode, locale: getLocale(), scope: "project_local" }),
    });
  } catch (e) {
    appendNotes([t("approval.saveFail", { msg: e.message })]);
  }
}

function setApprovalMode(mode, { persist = true, save = true } = {}) {
  const next = mode || "ask-on-state";
  if (next === "auto-approve" && !state.autoApproveAvailable) {
    state.approvalMode = "ask-on-danger";
  } else {
    state.approvalMode = next;
  }
  if (persist) localStorage.setItem("auc-approval-mode", state.approvalMode);
  for (const sel of ["#approval-mode-select", "#approval-mode-agent"]) {
    const el = $(sel);
    if (el && el.value !== state.approvalMode) el.value = state.approvalMode;
  }
  if (save && persist) void saveApprovalModeToServer(state.approvalMode);
}

function bindApprovalSelects() {
  for (const sel of ["#approval-mode-select", "#approval-mode-agent"]) {
    const el = $(sel);
    if (!el || el.dataset.bound) continue;
    el.dataset.bound = "1";
    el.addEventListener("change", () => {
      const mode = el.value;
      if (mode === "auto-approve") {
        if (!confirm(t("approval.autoApproveConfirm"))) {
          el.value = state.approvalMode;
          return;
        }
      }
      setApprovalMode(mode);
    });
  }
}


function populateRoleSelects() {
  if (!state.roles.some((r) => r.id === state.roleId)) {
    state.roleId = state.roles.find((r) => r.auto || r.id === "auto")?.id || "auto";
  }
  renderRoleTreeMenus();
}

function setRole(role, { persist = true } = {}) {
  state.roleId = role || "auto";
  if (persist) localStorage.setItem("auc-role", state.roleId);
  updateRoleTriggers();
  renderRoleTreeMenus();
  renderAgentProfile(state.info);
}

// ── 角色广场（agency-agents 风格：按细分领域分类 / 自动 / 自定义编辑）──
let rolePlazaFilter = { q: "", division: "all" };
let roleEditorMode = "create";
let roleEditorId = "";

function isAutoRole(r) {
  return Boolean(r?.auto || r?.id === "auto");
}

function catalogRoleCount() {
  return state.roles.filter((r) => !isAutoRole(r)).length;
}

function roleDivisionId(r) {
  if (isAutoRole(r)) return null;
  return r.division || "custom";
}

function divisionLabel(id) {
  const d = state.roleDivisions.find((x) => x.id === id);
  return d ? `${d.emoji || ""} ${d.label}`.trim() : id;
}

function setFacetChipContent(btn, label, count) {
  const showCount = count != null && count !== "";
  btn.innerHTML =
    `<span class="facet-chip-label">${escapeHtml(label)}</span>` +
    (showCount ? `<span class="facet-chip-badge">${count}</span>` : "");
}

function countModelsForFacet(models, facetKey, value) {
  if (value === "all") return models.length;
  return models.filter((m) =>
    facetKey === "series" ? modelSeries(m) === value : modelType(m) === value
  ).length;
}

function countRolesByDivision() {
  const counts = new Map();
  for (const r of state.roles) {
    const div = roleDivisionId(r);
    if (!div) continue;
    counts.set(div, (counts.get(div) || 0) + 1);
  }
  return counts;
}

function populateRoleDivisionFilters() {
  const wrap = $("#role-plaza-filters");
  if (!wrap) return;
  wrap.innerHTML = "";
  const counts = countRolesByDivision();
  const total = state.roles.length;
  if (rolePlazaFilter.division !== "all" && !(counts.get(rolePlazaFilter.division) > 0)) {
    rolePlazaFilter.division = "all";
  }
  const allBtn = document.createElement("button");
  allBtn.type = "button";
  allBtn.className = "facet-chip" + (rolePlazaFilter.division === "all" ? " active" : "");
  allBtn.dataset.division = "all";
  setFacetChipContent(allBtn, t("plaza.filterAll"), total);
  allBtn.disabled = total === 0;
  if (total === 0) allBtn.classList.add("is-disabled");
  allBtn.addEventListener("click", () => {
    if (total === 0) return;
    rolePlazaFilter.division = "all";
    populateRoleDivisionFilters();
    renderRolePlaza();
  });
  wrap.appendChild(allBtn);
  for (const d of state.roleDivisions) {
    const n = counts.get(d.id) || 0;
    const disabled = n === 0;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "facet-chip" + (rolePlazaFilter.division === d.id ? " active" : "");
    if (disabled) {
      btn.classList.add("is-disabled");
      btn.disabled = true;
    }
    btn.dataset.division = d.id;
    setFacetChipContent(btn, `${d.emoji || ""} ${d.label}`.trim(), n);
    btn.title = disabled ? "" : (d.description || "");
    if (!disabled) {
      btn.addEventListener("click", () => {
        rolePlazaFilter.division = d.id;
        populateRoleDivisionFilters();
        renderRolePlaza();
      });
    }
    wrap.appendChild(btn);
  }
}

function populateRoleEditorDivisions() {
  const sel = $("#role-editor-division");
  if (!sel) return;
  sel.innerHTML = state.roleDivisions
    .map((d) => `<option value="${escapeHtml(d.id)}">${escapeHtml(`${d.emoji || ""} ${d.label}`.trim())}</option>`)
    .join("");
  if (!sel.value) sel.value = "custom";
}

function makeRoleCard(r) {
  const isAuto = isAutoRole(r);
  const isCustom = !r.builtin && !isAuto;
  const card = document.createElement("button");
  card.type = "button";
  card.className = "role-card" + (isAuto ? " role-card-auto" : "") + (r.id === state.roleId ? " active" : "");
  card.dataset.roleId = r.id;
  const icon = r.emoji || (isCustom ? "🎭" : "◆");
  const label = r.label || r.id;
  const title = r.title || "";
  const showTitle = Boolean(title && title !== label);
  const autoDesc = t("plaza.roleAutoDesc", { n: catalogRoleCount() });
  const desc = isAuto ? r.description || autoDesc : r.description || "";
  const caps = isAuto
    ? `<span class="role-card-tag">${escapeHtml(t("plaza.roleAutoTag", { n: catalogRoleCount() }))}</span>`
    : (r.capabilities || []).slice(0, 3).map((c) => `<span class="role-card-tag">${escapeHtml(c)}</span>`).join("");
  const vibe = !isAuto && r.vibe ? `<div class="role-card-vibe">${escapeHtml(r.vibe)}</div>` : "";
  const when = r.when_to_use ? `<div class="role-card-when">${escapeHtml(r.when_to_use)}</div>` : "";
  card.innerHTML =
    `<div class="role-card-head"><span class="role-card-icon">${icon}</span><div>` +
    `<div class="role-card-label">${escapeHtml(label)}</div>` +
    (showTitle ? `<div class="role-card-title">${escapeHtml(title)}</div>` : "") +
    `</div></div>${vibe}${when}` +
    (desc ? `<div class="role-card-desc">${escapeHtml(desc)}</div>` : "") +
    (caps ? `<div class="role-card-tags">${caps}</div>` : "");
  card.addEventListener("click", (ev) => {
    if (ev.target.closest(".role-edit-btn")) return;
    void selectRoleFromPlaza(r.id);
  });
  if (!isAuto && !r.builtin) {
    const actions = document.createElement("div");
    actions.className = "role-card-actions";
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn ghost sm role-edit-btn";
    editBtn.textContent = t("plaza.roleEdit");
    editBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      void openRoleEditor(r.id);
    });
    actions.appendChild(editBtn);
    card.appendChild(actions);
  }
  return card;
}

function hideRolePlaza() {
  $("#role-plaza-overlay")?.classList.add("hidden");
}

function hideRoleEditor() {
  $("#role-editor-overlay")?.classList.add("hidden");
  $("#role-editor-error")?.classList.add("hidden");
}

function openRolePlaza() {
  rolePlazaFilter = { q: "", division: "all" };
  const search = $("#role-plaza-search");
  if (search) search.value = "";
  populateRoleDivisionFilters();
  renderRolePlaza();
  $("#role-plaza-overlay")?.classList.remove("hidden");
}

function appendPlazaSection(container, title, items, { autoSection = false, makeCard = makeRoleCard } = {}) {
  if (!items?.length) return;
  const section = document.createElement("section");
  section.className = "plaza-division-section" + (autoSection ? " plaza-auto-section" : "");
  const head = document.createElement("header");
  head.className = "plaza-division-head";
  head.innerHTML =
    `<span class="plaza-division-title-wrap">` +
    `<span class="plaza-division-title">${escapeHtml(title)}</span>` +
    `<span class="facet-chip-badge">${items.length}</span>` +
    `</span>`;
  section.appendChild(head);
  const grid = document.createElement("div");
  grid.className = "plaza-grid";
  grid.setAttribute("role", "listbox");
  for (const r of items) grid.appendChild(makeCard(r));
  section.appendChild(grid);
  container.appendChild(section);
}

function renderRolePlaza() {
  const container = $("#role-plaza-sections");
  const empty = $("#role-plaza-empty");
  if (!container) return;
  container.innerHTML = "";
  const q = rolePlazaFilter.q.trim().toLowerCase();
  const roles = state.roles.length ? state.roles : [];

  const filtered = roles.filter((r) => {
    if (rolePlazaFilter.division !== "all") {
      if (isAutoRole(r)) return false;
      if (roleDivisionId(r) !== rolePlazaFilter.division) return false;
    }
    const hay = `${r.label} ${r.title || ""} ${r.description || ""} ${r.vibe || ""} ${r.when_to_use || ""} ${(r.capabilities || []).join(" ")}`.toLowerCase();
    return !q || hay.includes(q);
  });

  const autoItems = filtered.filter(isAutoRole);
  const regular = filtered.filter((r) => !isAutoRole(r));

  if (rolePlazaFilter.division === "all" && autoItems.length) {
    appendPlazaSection(container, t("plaza.roleAuto"), autoItems, { autoSection: true });
  }

  const groups = new Map();
  for (const r of regular) {
    const div = roleDivisionId(r);
    if (!div) continue;
    if (!groups.has(div)) groups.set(div, []);
    groups.get(div).push(r);
  }

  const order = state.roleDivisions.length
    ? state.roleDivisions.map((d) => d.id)
    : ["specialized", "engineering", "operations", "education", "custom"];

  for (const divId of order) {
    const items = groups.get(divId);
    if (!items?.length) continue;
    appendPlazaSection(container, divisionLabel(divId), items);
  }

  if (empty) empty.classList.toggle("hidden", filtered.length > 0);
}

async function selectRoleFromPlaza(roleId) {
  setRole(roleId);
  if (roleId !== "auto") {
    try {
      await api(`/api/roles/${encodeURIComponent(roleId)}/activate?locale=${encodeURIComponent(getLocale())}`, { method: "POST" });
    } catch {
      /* 激活失败不阻断选用 */
    }
  }
  hideRolePlaza();
}

async function openRoleEditor(roleId = "") {
  roleEditorMode = roleId ? "edit" : "create";
  roleEditorId = roleId;
  const titleEl = $("#role-editor-title");
  const idInput = $("#role-editor-id");
  if (titleEl) titleEl.textContent = roleId ? t("plaza.roleEdit") : t("plaza.roleCreate");
  if (idInput) {
    idInput.value = roleId || "";
    idInput.disabled = Boolean(roleId);
  }
  $("#role-editor-label").value = "";
  $("#role-editor-title-field").value = "";
  $("#role-editor-desc").value = "";
  $("#role-editor-caps").value = "";
  $("#role-editor-emoji").value = "";
  $("#role-editor-vibe").value = "";
  $("#role-editor-when").value = "";
  $("#role-editor-persona").value = "";
  populateRoleEditorDivisions();
  if (!roleId) $("#role-editor-division").value = "custom";
  if (roleId) {
    try {
      const data = await api(`/api/roles/${encodeURIComponent(roleId)}?locale=${encodeURIComponent(getLocale())}`);
      $("#role-editor-label").value = data.label || "";
      $("#role-editor-title-field").value = data.title || "";
      $("#role-editor-desc").value = data.description || "";
      $("#role-editor-caps").value = (data.capabilities || []).join(", ");
      $("#role-editor-emoji").value = data.emoji || "";
      $("#role-editor-vibe").value = data.vibe || "";
      $("#role-editor-when").value = data.when_to_use || "";
      $("#role-editor-division").value = data.division || "custom";
      $("#role-editor-persona").value = data.persona || "";
    } catch (err) {
      const errEl = $("#role-editor-error");
      if (errEl) {
        errEl.textContent = err.message || String(err);
        errEl.classList.remove("hidden");
      }
      return;
    }
  }
  hideRolePlaza();
  $("#role-editor-overlay")?.classList.remove("hidden");
}

async function saveRoleEditor() {
  const errEl = $("#role-editor-error");
  errEl?.classList.add("hidden");
  const body = {
    role_id: ($("#role-editor-id")?.value || "").trim(),
    label: ($("#role-editor-label")?.value || "").trim(),
    title: ($("#role-editor-title-field")?.value || "").trim(),
    description: ($("#role-editor-desc")?.value || "").trim(),
    capabilities: ($("#role-editor-caps")?.value || "").trim(),
    division: $("#role-editor-division")?.value || "custom",
    emoji: ($("#role-editor-emoji")?.value || "").trim(),
    vibe: ($("#role-editor-vibe")?.value || "").trim(),
    when_to_use: ($("#role-editor-when")?.value || "").trim(),
    persona: ($("#role-editor-persona")?.value || "").trim(),
    activate: true,
  };
  try {
    const localeQ = `locale=${encodeURIComponent(getLocale())}`;
    const data =
      roleEditorMode === "edit"
        ? await api(`/api/roles/${encodeURIComponent(roleEditorId)}?${localeQ}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          })
        : await api(`/api/roles?${localeQ}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
    if (data.roles) state.roles = data.roles;
    if (data.role_divisions) state.roleDivisions = data.role_divisions;
    populateRoleSelects();
    populateRoleDivisionFilters();
    setRole(data.role_id || body.role_id);
    hideRoleEditor();
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message || String(err);
      errEl.classList.remove("hidden");
    }
  }
}

function bindRolePlaza() {
  $("#role-pill")?.addEventListener("click", openRolePlaza);
  $("#role-plaza-close")?.addEventListener("click", hideRolePlaza);
  $("#role-plaza-overlay")?.addEventListener("click", (ev) => {
    if (ev.target.id === "role-plaza-overlay") hideRolePlaza();
  });
  $("#role-plaza-create")?.addEventListener("click", () => void openRoleEditor());
  $("#role-plaza-search")?.addEventListener("input", (ev) => {
    rolePlazaFilter.q = ev.target.value;
    renderRolePlaza();
  });
  $("#role-editor-cancel")?.addEventListener("click", hideRoleEditor);
  $("#role-editor-save")?.addEventListener("click", () => void saveRoleEditor());
  $("#role-editor-overlay")?.addEventListener("click", (ev) => {
    if (ev.target.id === "role-editor-overlay") hideRoleEditor();
  });
}

// ── 技能广场（按角色分类 / 自动或手动选择）──
let skillPlazaFilter = { q: "", division: "all" };

function skillDivisionId(sk) {
  return sk.division || "custom";
}

function countSkillsByDivision() {
  const counts = new Map();
  for (const sk of state.skills) {
    const div = skillDivisionId(sk);
    counts.set(div, (counts.get(div) || 0) + 1);
  }
  return counts;
}

function updateSkillTriggers() {
  renderChoicePill($("#skill-pill"), "skill", skillHeaderValue());
}

async function persistSkillSettings() {
  localStorage.setItem("auc-skill-mode", state.skillMode);
  localStorage.setItem("auc-skill-pinned", JSON.stringify(state.skillPinned));
  try {
    await api("/api/settings/skills", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: state.skillMode, pinned: state.skillPinned }),
    });
  } catch {
    /* 离线或沙盒只读时不阻断 UI */
  }
  updateSkillTriggers();
}

function hideSkillPlaza() {
  $("#skill-plaza-overlay")?.classList.add("hidden");
}

function openSkillPlaza() {
  skillPlazaFilter = { q: "", division: "all" };
  const search = $("#skill-plaza-search");
  if (search) search.value = "";
  populateSkillModeBar();
  populateSkillDivisionFilters();
  renderSkillPlaza();
  $("#skill-plaza-overlay")?.classList.remove("hidden");
}

function populateSkillModeBar() {
  const wrap = $("#skill-mode-bar");
  if (!wrap) return;
  wrap.innerHTML = "";
  for (const mode of ["auto", "manual"]) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "facet-chip" + (state.skillMode === mode ? " active" : "");
    btn.textContent = mode === "auto" ? t("plaza.skillAuto") : t("plaza.skillManual");
    btn.title = mode === "auto" ? t("plaza.skillAutoDesc") : t("plaza.skillManualDesc");
    btn.addEventListener("click", () => {
      state.skillMode = mode;
      populateSkillModeBar();
      renderSkillPlaza();
      void persistSkillSettings();
    });
    wrap.appendChild(btn);
  }
}

function populateSkillDivisionFilters() {
  const wrap = $("#skill-plaza-filters");
  if (!wrap) return;
  wrap.innerHTML = "";
  const counts = countSkillsByDivision();
  const total = state.skills.length;
  if (skillPlazaFilter.division !== "all" && !(counts.get(skillPlazaFilter.division) > 0)) {
    skillPlazaFilter.division = "all";
  }
  const allBtn = document.createElement("button");
  allBtn.type = "button";
  allBtn.className = "facet-chip" + (skillPlazaFilter.division === "all" ? " active" : "");
  setFacetChipContent(allBtn, t("plaza.filterAll"), total);
  allBtn.disabled = total === 0;
  if (total === 0) allBtn.classList.add("is-disabled");
  allBtn.addEventListener("click", () => {
    if (total === 0) return;
    skillPlazaFilter.division = "all";
    populateSkillDivisionFilters();
    renderSkillPlaza();
  });
  wrap.appendChild(allBtn);
  for (const d of state.roleDivisions) {
    const n = counts.get(d.id) || 0;
    const disabled = n === 0;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "facet-chip" + (skillPlazaFilter.division === d.id ? " active" : "");
    if (disabled) {
      btn.classList.add("is-disabled");
      btn.disabled = true;
    }
    setFacetChipContent(btn, `${d.emoji || ""} ${d.label}`.trim(), n);
    if (!disabled) {
      btn.addEventListener("click", () => {
        skillPlazaFilter.division = d.id;
        populateSkillDivisionFilters();
        renderSkillPlaza();
      });
    }
    wrap.appendChild(btn);
  }
}

function isSkillPinned(name) {
  return state.skillPinned.includes(name);
}

function toggleSkillPin(name) {
  const idx = state.skillPinned.indexOf(name);
  if (idx >= 0) {
    state.skillPinned.splice(idx, 1);
  } else {
    state.skillPinned.push(name);
  }
  void persistSkillSettings();
  renderSkillPlaza();
}

function makeSkillCard(sk) {
  const pinned = isSkillPinned(sk.name);
  const card = document.createElement("div");
  card.className =
    "role-card skill-card" +
    (pinned ? " pinned" : "") +
    (!sk.for_role ? " disabled-for-role" : "");
  const icon = sk.emoji || "⚡";
  const desc = (sk.description || "").slice(0, 160);
  const tags = [];
  if (sk.builtin) tags.push(t("plaza.skillBuiltin"));
  if (sk.for_role) tags.push(t("plaza.skillForRole"));
  const roleTags = (sk.roles || []).slice(0, 3);
  card.innerHTML =
    `<div class="role-card-head">` +
    `<span class="role-card-icon">${escapeHtml(icon)}</span>` +
    `<span class="role-card-label">${escapeHtml(sk.name)}</span>` +
    `</div>` +
    `<div class="role-card-desc">${escapeHtml(desc)}</div>` +
    `<div class="role-card-tags">` +
    tags.map((x) => `<span class="role-card-tag">${escapeHtml(x)}</span>`).join("") +
    roleTags.map((x) => `<span class="role-card-tag">${escapeHtml(x)}</span>`).join("") +
    `</div>`;
  if (state.skillMode === "manual") {
    const pinRow = document.createElement("label");
    pinRow.className = "skill-card-pin";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = pinned;
    cb.addEventListener("change", () => toggleSkillPin(sk.name));
    pinRow.appendChild(cb);
    pinRow.appendChild(document.createTextNode(t("plaza.skillPin")));
    card.appendChild(pinRow);
  }
  if (sk.source_url) {
    const link = document.createElement("a");
    link.className = "role-card-tag";
    link.href = sk.source_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "GitHub";
    card.querySelector(".role-card-tags")?.appendChild(link);
  }
  return card;
}

function renderSkillPlaza() {
  const container = $("#skill-plaza-sections");
  const empty = $("#skill-plaza-empty");
  if (!container) return;
  container.innerHTML = "";
  const q = skillPlazaFilter.q.trim().toLowerCase();
  const filtered = state.skills.filter((sk) => {
    if (skillPlazaFilter.division !== "all" && skillDivisionId(sk) !== skillPlazaFilter.division) {
      return false;
    }
    const hay = `${sk.name} ${sk.description || ""} ${(sk.triggers || []).join(" ")} ${(sk.roles || []).join(" ")}`.toLowerCase();
    return !q || hay.includes(q);
  });
  const groups = new Map();
  for (const sk of filtered) {
    const div = skillDivisionId(sk);
    if (!groups.has(div)) groups.set(div, []);
    groups.get(div).push(sk);
  }
  const order = state.roleDivisions.length
    ? state.roleDivisions.map((d) => d.id)
    : ["design", "engineering", "custom"];
  for (const divId of order) {
    const items = groups.get(divId);
    if (!items?.length) continue;
    appendPlazaSection(container, divisionLabel(divId), items, { makeCard: makeSkillCard });
  }
  if (empty) empty.classList.toggle("hidden", filtered.length > 0);
}

function bindSkillPlaza() {
  $("#skill-pill")?.addEventListener("click", openSkillPlaza);
  $("#skill-plaza-close")?.addEventListener("click", hideSkillPlaza);
  $("#skill-plaza-overlay")?.addEventListener("click", (ev) => {
    if (ev.target.id === "skill-plaza-overlay") hideSkillPlaza();
  });
  $("#skill-plaza-search")?.addEventListener("input", (ev) => {
    skillPlazaFilter.q = ev.target.value;
    renderSkillPlaza();
  });
  bindChoicePillKeyboard();
}

function bindChoicePillKeyboard() {
  for (const id of ["role-pill", "skill-pill", "model-pill"]) {
    const el = $(`#${id}`);
    if (!el || el.dataset.kbBound) continue;
    el.dataset.kbBound = "1";
    el.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        el.click();
      }
    });
  }
}

// ── 模型广场（配置连接后自动加载；默认 auto:balanced）──
let modelPlazaSelection = "";
let modelPlazaFilter = { q: "", series: "all", type: "all" };

function hideModelPlaza() {
  $("#model-plaza-overlay")?.classList.add("hidden");
  $("#model-plaza-error")?.classList.add("hidden");
}

function selectPlazaModel(model) {
  modelPlazaSelection = model;
  $("#model-plaza-chips")?.querySelectorAll(".model-chip").forEach((c) => {
    c.classList.toggle("active", c.dataset.model === model);
  });
  $("#model-plaza-auto-row")?.querySelectorAll(".model-chip.auto").forEach((c) => {
    c.classList.toggle("active", c.dataset.model === model);
  });
}

function buildPlazaModelFacets(models) {
  const facets = $("#model-plaza-facets");
  if (!facets) return;
  facets.innerHTML = "";
  const presentSeries = new Set(models.map(modelSeries));
  const seriesOrder = orderedModelSeries(models).filter((n) => presentSeries.has(n));
  const presentTypes = new Set(models.map(modelType));
  const typeOrder = ["text", "image", "speech", "video", "embedding", "reranking", "ocr"].filter((tp) =>
    presentTypes.has(tp)
  );

  function addFacetRow(facetKey, labelText, values, labelOf) {
    const row = document.createElement("div");
    row.className = "model-facet";
    const lab = document.createElement("span");
    lab.className = "model-facet-label";
    lab.textContent = labelText;
    row.appendChild(lab);
    const chips = document.createElement("div");
    chips.className = "model-facet-chips";
    for (const v of ["all", ...values]) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "facet-chip" + (modelPlazaFilter[facetKey] === v ? " active" : "");
      b.dataset.value = v;
      const chipLabel = v === "all" ? t("model.facet.all") : labelOf(v);
      setFacetChipContent(b, chipLabel, countModelsForFacet(models, facetKey, v));
      b.addEventListener("click", () => {
        modelPlazaFilter[facetKey] = v;
        chips.querySelectorAll(".facet-chip").forEach((c) =>
          c.classList.toggle("active", c.dataset.value === v)
        );
        applyPlazaModelFilter();
      });
      chips.appendChild(b);
    }
    row.appendChild(chips);
    facets.appendChild(row);
  }

  if (seriesOrder.length > 1) {
    addFacetRow("series", t("model.facet.series"), seriesOrder, seriesLabel);
  }
  if (typeOrder.length > 1) {
    addFacetRow("type", t("model.facet.type"), typeOrder, (v) => t("model.type." + v));
  }
}

function applyPlazaModelFilter() {
  const body = $("#model-plaza-chips");
  const emptyEl = $("#model-plaza-empty");
  const countEl = $("#model-plaza-count");
  if (!body) return;
  const q = modelPlazaFilter.q.trim().toLowerCase();
  let shown = 0;
  body.querySelectorAll(".model-chip").forEach((c) => {
    const id = c.dataset.model || "";
    const hit =
      (!q || id.toLowerCase().includes(q)) &&
      (modelPlazaFilter.series === "all" || modelSeries(id) === modelPlazaFilter.series) &&
      (modelPlazaFilter.type === "all" || modelType(id) === modelPlazaFilter.type);
    c.classList.toggle("hidden", !hit);
    if (hit) shown += 1;
  });
  if (emptyEl) emptyEl.classList.toggle("hidden", shown !== 0);
  const filtered = q || modelPlazaFilter.series !== "all" || modelPlazaFilter.type !== "all";
  if (countEl) {
    countEl.textContent = filtered
      ? t("model.filterCount", { shown, total: discoveredModels.length })
      : t("model.modelCount", { n: discoveredModels.length });
  }
}

function renderPlazaModelChips(models) {
  const body = $("#model-plaza-chips");
  if (!body) return;
  discoveredModels = models.slice();
  body.innerHTML = "";
  const current = modelPlazaSelection;
  for (const m of models) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "model-chip" + (m === current ? " active" : "");
    chip.dataset.model = m;
    chip.textContent = m;
    chip.title = m;
    chip.addEventListener("click", () => selectPlazaModel(m));
    body.appendChild(chip);
  }
  const search = $("#model-plaza-search");
  if (search) search.value = modelPlazaFilter.q;
  buildPlazaModelFacets(models);
  applyPlazaModelFilter();
}

async function discoverModelsForPlaza() {
  const hintEl = $("#model-plaza-hint");
  const s = modelSettingsCache || {};
  const provider = s.provider || state.info?.model?.provider || "openai";
  const base_url = (s.base_url || "").trim();
  const key = (s.api_key || "").trim();
  if (!base_url) {
    if (hintEl) hintEl.textContent = t("model.discoverNeedBase");
    return;
  }
  if (hintEl) hintEl.textContent = t("model.discovering");
  try {
    const data = await api("/api/settings/model/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, base_url, api_key: key || undefined }),
    });
    if (data.ok && Array.isArray(data.models) && data.models.length) {
      renderPlazaModelChips(data.models);
      if (hintEl) hintEl.textContent = t("model.discoverOk", { n: data.models.length });
    } else if (hintEl) {
      hintEl.textContent = data.error ? t("model.discoverFailManual", { msg: data.error }) : t("model.discoverEmpty");
    }
  } catch (err) {
    if (hintEl) hintEl.textContent = t("model.discoverFailManual", { msg: err.message || String(err) });
  }
}

async function openModelPlaza() {
  try {
    if (!modelSettingsCache) {
      modelSettingsCache = await api("/api/settings/model");
    }
  } catch (err) {
    alert(t("model.loadFail", { msg: err.message || String(err) }));
    return;
  }
  modelPlazaSelection = modelSettingsCache.model || state.info?.model?.model || "auto:balanced";
  if (!modelPlazaSelection) modelPlazaSelection = "auto:balanced";
  modelPlazaFilter = { q: "", series: "all", type: "all" };
  selectPlazaModel(modelPlazaSelection);
  $("#model-plaza-overlay")?.classList.remove("hidden");
  void discoverModelsForPlaza();
}

async function saveModelPlaza() {
  const errEl = $("#model-plaza-error");
  errEl?.classList.add("hidden");
  const model = modelPlazaSelection || "auto:balanced";
  const s = modelSettingsCache || {};
  const body = {
    provider: s.provider || "openai",
    model,
    base_url: s.base_url || "",
    scope: "project_local",
  };
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
      };
      updateModelPillDisplay(data.model);
      renderAgentProfile(state.info);
    }
    hideModelPlaza();
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message || String(err);
      errEl.classList.remove("hidden");
    }
  }
}

function bindModelPlaza() {
  $("#model-pill")?.addEventListener("click", () => void openModelPlaza());
  $("#model-conn-btn")?.addEventListener("click", () => void openModelSettings());
  $("#model-plaza-close")?.addEventListener("click", hideModelPlaza);
  $("#model-plaza-cancel")?.addEventListener("click", hideModelPlaza);
  $("#model-plaza-save")?.addEventListener("click", () => void saveModelPlaza());
  $("#model-plaza-conn")?.addEventListener("click", () => {
    hideModelPlaza();
    void openModelSettings();
  });
  $("#model-plaza-overlay")?.addEventListener("click", (ev) => {
    if (ev.target.id === "model-plaza-overlay") hideModelPlaza();
  });
  $("#model-plaza-search")?.addEventListener("input", (ev) => {
    modelPlazaFilter.q = ev.target.value;
    applyPlazaModelFilter();
  });
  $("#model-plaza-auto-row")?.querySelectorAll(".model-chip.auto").forEach((chip) => {
    chip.addEventListener("click", () => selectPlazaModel(chip.dataset.model || "auto:balanced"));
  });
}

async function loadInfo() {
  state.info = await api(`/api/info?locale=${encodeURIComponent(getLocale())}`);
  state.workModes = state.info.work_modes || [];
  if (state.info.approval) {
    state.approvalModes = state.info.approval.modes || [];
    state.autoApproveAvailable = state.info.approval.auto_approve_available !== false;
    const stored = localStorage.getItem("auc-approval-mode");
    state.approvalMode = stored || state.info.approval.mode || "ask-on-state";
  }
  state.roles = state.info.roles || [];
  state.roleDivisions = state.info.role_divisions || [];
  state.skills = state.info.skills || [];
  if (state.info.skill_settings) {
    state.skillMode = state.info.skill_settings.mode || state.skillMode;
    state.skillPinned = state.info.skill_settings.pinned || state.skillPinned;
    localStorage.setItem("auc-skill-mode", state.skillMode);
    localStorage.setItem("auc-skill-pinned", JSON.stringify(state.skillPinned));
  }
  const storedRole = localStorage.getItem("auc-role");
  if (storedRole && state.roles.some((r) => r.id === storedRole)) {
    state.roleId = storedRole;
  } else {
    const activeFromApi = state.info.roles?.find((r) => r.active);
    if (activeFromApi) {
      state.roleId = activeFromApi.id;
    } else if (state.info.agent?.active_role) {
      state.roleId = state.info.agent.active_role;
    } else if (!storedRole) {
      state.roleId = "auto";
    }
  }
  state.activeConversationId = state.info.conversation?.active_id || null;
  renderVersionInfo(state.info);
  updateModelPillDisplay();
  $("#ws-pill").textContent = state.info.workspace.display;
  populateWorkModeSelects();
  bindWorkModeSelects();
  populateApprovalSelects();
  bindApprovalSelects();
  populateRoleSelects();
  bindRoleTreeSelects();
  updateRoleTriggers();
  updateSkillTriggers();
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
    if (release.update_available && release.latest_version) {
      versionEl.textContent = t("update.versionArrow", { current, latest: release.latest_version });
      versionEl.title = t("update.hasUpdate", { cmd: release.install_cmd || "pip install -U ufy-auc" });
    } else {
      versionEl.textContent = `v${current}`;
      versionEl.title = release.latest_version
        ? t("update.upToDate", { current, latest: release.latest_version })
        : t("update.current", { current });
    }
    versionEl.classList.toggle("has-update", !!release.update_available);
  }
  renderUpdateNotices(release);
}

async function refreshReleaseInfo({ force = false } = {}) {
  try {
    const q = force ? "?force=1" : "";
    const release = await api(`/api/release${q}`);
    if (state.info) {
      state.info.release = release;
      state.info.version = release.current_version || state.info.version;
    }
    renderVersionInfo(state.info || { release, version: release.current_version });
    return release;
  } catch {
    return null;
  }
}

const RELEASE_RECHECK_MS = 30 * 60 * 1000;
let releaseRecheckTimer = null;

function scheduleReleaseRecheck() {
  if (releaseRecheckTimer) clearInterval(releaseRecheckTimer);
  releaseRecheckTimer = setInterval(() => {
    void refreshReleaseInfo({ force: true });
  }, RELEASE_RECHECK_MS);
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
    headline: t("update.headline", { latest, current }),
    detail: t("update.detail"),
    cmd,
    chatHeadline: t("update.chatHeadline", { latest, current }),
    chatDetail: t("update.chatDetail"),
  };
}

let upgradeInFlight = false;

function setUpgradeButtonsBusy(busy) {
  upgradeInFlight = busy;
  for (const id of ["update-banner-upgrade", "chat-update-upgrade", "chat-update-msg-upgrade"]) {
    const btn = $(`#${id}`);
    if (!btn) continue;
    btn.disabled = busy;
    if (id === "update-banner-upgrade" || id === "chat-update-upgrade") {
      btn.textContent = busy ? t("update.upgrading") : t("update.upgrade");
    }
  }
}

function showUpgradeStatus(text, kind = "") {
  const el = $("#update-upgrade-status");
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("hidden", !text);
  el.classList.toggle("ok", kind === "ok");
  el.classList.toggle("err", kind === "err");
}

async function runOneClickUpgrade() {
  if (upgradeInFlight) return;
  setUpgradeButtonsBusy(true);
  showUpgradeStatus(t("update.pipBusy"));
  try {
    const data = await api("/api/release/upgrade", { method: "POST" });
    if (data.skipped) {
      showUpgradeStatus(data.message || t("update.alreadyLatest"), "ok");
      await refreshReleaseInfo({ force: true });
      return;
    }
    if (data.ok) {
      showUpgradeStatus(data.message || t("update.success"), "ok");
      if (state.info) state.info.release = data.release || state.info.release;
      renderVersionInfo(state.info || { release: data.release });
      const msg = $("#chat-update-msg");
      if (msg) {
        const status = document.createElement("p");
        status.className = "update-msg-body";
        status.textContent = data.message || t("update.success");
        msg.appendChild(status);
      }
    } else {
      showUpgradeStatus(data.message || t("update.fail"), "err");
    }
  } catch (err) {
    showUpgradeStatus(err.message || String(err), "err");
  } finally {
    setUpgradeButtonsBusy(false);
  }
}

function dismissUpdateNotice(release) {
  if (release?.latest_version) {
    localStorage.setItem(`auc-update-dismiss-${release.latest_version}`, "1");
  }
  $("#update-banner")?.classList.add("hidden");
  $("#chat-update-notice")?.classList.add("hidden");
  $("#chat-update-msg")?.remove();
  showUpgradeStatus("");
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
      `<div class="update-msg-title">${t("update.title")}</div>` +
      `<p class="update-msg-body">${copy.chatHeadline} ${copy.chatDetail}</p>` +
      `<code class="update-msg-cmd">${copy.cmd}</code>` +
      `<div class="update-msg-actions">` +
      `<button type="button" class="btn primary sm" id="chat-update-msg-upgrade">${t("update.upgrade")}</button>` +
      `</div>`;
    $("#chat-update-msg-upgrade")?.addEventListener("click", () => void runOneClickUpgrade());
  }
}

function bindUpdateBanner() {
  const dismiss = () => dismissUpdateNotice(state.info?.release);
  $("#update-banner-dismiss")?.addEventListener("click", dismiss);
  $("#chat-update-dismiss")?.addEventListener("click", dismiss);
  $("#update-banner-upgrade")?.addEventListener("click", () => void runOneClickUpgrade());
  $("#chat-update-upgrade")?.addEventListener("click", () => void runOneClickUpgrade());
  $("#version")?.addEventListener("click", () => void refreshReleaseInfo({ force: true }));
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
    btn.title = modelKeyVisible ? t("model.hideKey") : t("model.showKey");
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

let discoveredModels = [];

// 从模型 ID 推断「系列/厂商」（顺序敏感：先匹配先命中）。
const MODEL_SERIES_RULES = [
  ["OpenAI", /(^|[-/])(gpt|chatgpt|o1|o3|o4|davinci|babbage)|whisper|dall-?e|gpt-image|text-embedding|tts-|\bsora\b/],
  ["Anthropic", /claude/],
  ["Google", /gemini|gemma|palm|imagen|\bveo\b/],
  ["DeepSeek", /deepseek/],
  ["Qwen", /qwen|qwq|qvq/],
  ["Grok", /grok/],
  ["Llama", /llama|codellama|meta-llama/],
  ["Mistral", /mistral|mixtral|codestral|pixtral|ministral/],
  ["Cohere", /cohere|(^|[-/])command|rerank-(english|multilingual|v)/],
  ["Moonshot", /moonshot|kimi/],
  ["Zhipu", /\bglm|chatglm|zhipu|cogview|cogvideo/],
  ["MiniMax", /minimax|abab|hailuo/],
  ["Baichuan", /baichuan/],
  ["Yi", /(^|[-/])yi-|01-ai|01ai/],
  ["StepFun", /(^|[-/])step-/],
  ["ByteDance", /doubao|seedance|seedream|jimeng|(^|[-/])seed-/],
  ["Baidu", /ernie|wenxin/],
  ["Tencent", /hunyuan/],
  ["Nvidia", /nvidia|nemotron/],
  ["Microsoft", /(^|[-/])phi-/],
  ["Stability", /stable-?diffusion|sdxl|(^|[-/])sd3|(^|[-/])sd-/],
  ["BAAI", /(^|[-/])bge-|baai/],
  ["Perplexity", /perplexity|pplx/],
  ["Amazon", /amazon|bedrock|titan/],
  ["Groq", /groq/],
  ["Fireworks", /fireworks/],
  ["Together", /together/],
  ["Cerebras", /cerebras/],
];

const VENDOR_PREFIX_SERIES = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
  gemini: "Google",
  meta: "Meta",
  "meta-llama": "Meta",
  deepseek: "DeepSeek",
  qwen: "Qwen",
  alibaba: "Qwen",
  dashscope: "Qwen",
  mistralai: "Mistral",
  mistral: "Mistral",
  moonshotai: "Moonshot",
  moonshot: "Moonshot",
  zhipu: "Zhipu",
  zai: "Zhipu",
  glm: "Zhipu",
  cohere: "Cohere",
  grok: "Grok",
  xai: "Grok",
  bytedance: "ByteDance",
  doubao: "ByteDance",
  volcengine: "ByteDance",
  baidu: "Baidu",
  tencent: "Tencent",
  minimax: "MiniMax",
  yi: "Yi",
  "01ai": "Yi",
  perplexity: "Perplexity",
  amazon: "Amazon",
  bedrock: "Amazon",
  azure: "Microsoft",
  microsoft: "Microsoft",
  nvidia: "Nvidia",
  huggingface: "HuggingFace",
  hf: "HuggingFace",
  together: "Together",
  fireworks: "Fireworks",
  groq: "Groq",
  cerebras: "Cerebras",
  openrouter: "OpenRouter",
};

function titleCaseVendor(v) {
  return v
    .split(/[-_]/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

function inferSeriesFromLeadingToken(s) {
  const m = s.match(/^([a-z][a-z0-9]*)/);
  if (!m) return "通用";
  const token = m[1];
  if (VENDOR_PREFIX_SERIES[token]) return VENDOR_PREFIX_SERIES[token];
  for (const [name, re] of MODEL_SERIES_RULES) if (re.test(token)) return name;
  return titleCaseVendor(token);
}

function orderedModelSeries(models) {
  const present = new Set(models.map(modelSeries));
  const known = MODEL_SERIES_RULES.map(([n]) => n);
  return [
    ...known.filter((n) => present.has(n)),
    ...[...present].filter((n) => !known.includes(n)).sort((a, b) => a.localeCompare(b)),
  ];
}

// 从模型 ID 推断「能力类型」（顺序敏感）。
const MODEL_TYPE_RULES = [
  ["embedding", /embed|(^|[-/])bge-|(^|[-/])gte-|(^|[-/])m3e/],
  ["reranking", /rerank/],
  ["ocr", /ocr/],
  ["speech", /whisper|(^|[-/])tts|audio|speech|voice|realtime/],
  ["video", /video|\bsora\b|\bveo\b|kling|cogvideo|hailuo|seedance|runway/],
  ["image", /dall-?e|gpt-image|(^|[-/])image|flux|midjourney|stable-?diffusion|sdxl|(^|[-/])sd3|(^|[-/])sd-|seedream|jimeng|cogview|kolors|imagen|recraft|ideogram/],
];

function modelSeries(id) {
  const s = String(id || "").toLowerCase().trim();
  if (!s || s.startsWith("auto")) return "Auto";
  const slashIdx = s.indexOf("/");
  if (slashIdx > 0) {
    const vendor = s.slice(0, slashIdx).replace(/^@/, "");
    if (VENDOR_PREFIX_SERIES[vendor]) return VENDOR_PREFIX_SERIES[vendor];
    return titleCaseVendor(vendor);
  }
  for (const [name, re] of MODEL_SERIES_RULES) if (re.test(s)) return name;
  return inferSeriesFromLeadingToken(s);
}

function modelType(id) {
  const s = String(id || "").toLowerCase();
  for (const [name, re] of MODEL_TYPE_RULES) if (re.test(s)) return name;
  return "text";
}

function seriesLabel(v) {
  return v;
}

function updateModelConnStatus(text) {
  const el = $("#model-settings-conn-status");
  if (el) el.textContent = text || "";
}

function updateModelCurrentDisplay(model) {
  const el = $("#model-settings-current-model");
  if (el) el.textContent = model || "—";
}

// auto=true：打开/保存连接后静默探测，仅更新缓存与状态行。
async function discoverModels({ auto = false } = {}) {
  const statusEl = $("#model-settings-conn-status");
  const provider = $("#model-settings-provider")?.value || "openai";
  const base_url = $("#model-settings-base-url")?.value?.trim() || "";
  const key = $("#model-settings-api-key")?.value?.trim() || "";
  if (!base_url) {
    discoveredModels = [];
    if (!auto && statusEl) statusEl.textContent = t("model.discoverNeedBase");
    else if (auto && statusEl) statusEl.textContent = "";
    return;
  }
  if (auto && statusEl) statusEl.textContent = t("model.discovering");
  try {
    const data = await api("/api/settings/model/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, base_url, api_key: key || undefined }),
    });
    if (data.ok && Array.isArray(data.models) && data.models.length) {
      discoveredModels = data.models.slice();
      if (statusEl) statusEl.textContent = t("model.connReady", { n: data.models.length });
      if (!$("#model-plaza-overlay")?.classList.contains("hidden")) {
        renderPlazaModelChips(discoveredModels);
      }
    } else {
      discoveredModels = [];
      if (statusEl) {
        statusEl.textContent = auto
          ? ""
          : data.error
          ? t("model.discoverFailManual", { msg: data.error })
          : t("model.discoverEmpty");
      }
    }
  } catch (err) {
    discoveredModels = [];
    if (statusEl && !auto) {
      statusEl.textContent = t("model.discoverFailManual", { msg: err.message || String(err) });
    }
  }
}

function renderModelLayers(s) {
  const layers = s.layers || {};
  const activeScope = s.active_scope || layers.active_scope;
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
    alert(t("model.loadFail", { msg: err.message }));
    return;
  }
  const s = modelSettingsCache;
  $("#model-settings-provider").value = s.provider || "openai";
  $("#model-settings-base-url").value = s.base_url || "";
  // 后端不再回显明文 key；留空表示沿用已配置密钥
  const keyInput = $("#model-settings-api-key");
  keyInput.value = "";
  keyInput.placeholder = s.api_key_set ? s.api_key_masked || "········" : "";
  updateModelCurrentDisplay(s.model || "auto:balanced");
  setModelKeyVisible(false);
  renderModelLayers(s);
  const hint = $("#model-settings-key-hint");
  if (hint) {
    hint.textContent = s.api_key_set
      ? t("model.keyConfigured", { masked: s.api_key_masked })
      : t("model.keyMissing");
  }
  updateModelConnStatus(
    discoveredModels.length ? t("model.connReady", { n: discoveredModels.length }) : t("model.connIdle")
  );
  overlay.classList.remove("hidden");
  $("#model-settings-base-url")?.focus();
  if ((s.base_url || "").trim() && ((s.api_key || "").trim() || s.api_key_set)) {
    void discoverModels({ auto: true });
  }
}

async function saveModelSettings() {
  const errEl = $("#model-settings-error");
  errEl?.classList.add("hidden");
  const body = {
    provider: $("#model-settings-provider")?.value || "openai",
    model: modelSettingsCache?.model || state.info?.model?.model || "auto:balanced",
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
      updateModelPillDisplay(data.model);
      renderAgentProfile(state.info);
    }
    hideModelSettings();
    void discoverModels({ auto: true });
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message || String(err);
      errEl.classList.remove("hidden");
    }
  }
}

function applyAilabPreset() {
  $("#model-settings-provider").value = "openai";
  $("#model-settings-base-url").value = "http://ailab.hcrdi.com/api";
}

function bindModelSettings() {
  setButtonIcon($("#model-settings-key-toggle"), "eye", { size: 16 });
  $("#model-settings-cancel")?.addEventListener("click", hideModelSettings);
  $("#model-settings-save")?.addEventListener("click", () => void saveModelSettings());
  $("#model-settings-ailab-preset")?.addEventListener("click", applyAilabPreset);
  $("#model-settings-open-plaza")?.addEventListener("click", () => {
    hideModelSettings();
    void openModelPlaza();
  });
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
    const info = await api(`/api/info?locale=${encodeURIComponent(getLocale())}`);
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
    <button type="button" data-action="rename">${t("ws.rename")}</button>
    <button type="button" data-action="delete" class="danger">${t("ws.delete")}</button>`;
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
  const label = entry.type === "dir" ? t("ws.kind.folder") : t("ws.kind.file");
  const ok = window.confirm(t("ws.deleteConfirm", { kind: label, name: entry.name }));
  if (!ok) return;
  try {
    await api(`/api/workspace/path?path=${encodeURIComponent(entry.path)}`, {
      method: "DELETE",
    });
    removePathsAfterDelete(entry.path, entry.type === "dir");
    await loadTree(state.treePath);
  } catch (e) {
    window.alert(e.message || t("ws.deleteFail"));
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
  if (title) title.textContent = t("ws.rename");
  if (hint) hint.textContent = t("ws.renameOld", { name: entry.name });
  if (confirmBtn) confirmBtn.textContent = t("common.confirm");
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
        <button type="button" class="icon-btn tree-action-rename" data-i18n-title="ws.rename"></button>
        <button type="button" class="icon-btn tree-action-delete" data-i18n-title="ws.delete"></button>
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
  applyI18n(root);
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
    throw new Error(t("ws.invalidName"));
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
  if (title) title.textContent = mode === "folder" ? t("ws.createFolder") : t("ws.createFile");
  if (confirmBtn) confirmBtn.textContent = t("ws.create");
  if (hint) {
    const loc = state.treePath === "." ? t("ws.root") : state.treePath;
    hint.textContent = t("ws.createUnder", { loc });
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
        err.textContent = e.message || t("ws.renameFail");
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
          err.textContent = t("ws.exists");
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
      err.textContent = e.message || t("ws.createFail");
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
  hideDocumentPreview();
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
  hideDocumentPreview();
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

function hideDocPreview() {
  hideDocumentPreview();
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

function showAppPreview(url, title = t("editor.preview")) {
  hideImagePreview();
  hideDocPreview();
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
  alert(t("project.needBackend"));
}

async function loadProjects() {
  const data = await api("/api/projects");
  state.projects = data.projects || [];
  const list = $("#project-list");
  if (!list) return;
  list.innerHTML = "";
  if (!state.projects.length) {
    list.innerHTML =
      `<div class="p-meta" style="padding:.35rem">${escapeHtml(t("project.empty"))}<br>${escapeHtml(t("project.emptyHint"))}</div>`;
    return;
  }
  for (const p of state.projects) {
    const card = document.createElement("div");
    card.className = "project-card";
    const runBadge = p.running ? `<span class="badge-run">${t("project.running")}</span>` : "";
    card.innerHTML = `
      <div class="p-name">${p.name}${runBadge}</div>
      <div class="p-meta">${p.kind} · ${p.description || p.entry}</div>
      <div class="p-actions">
        <button type="button" class="btn primary sm" data-act="run">${t("project.run")}</button>
        ${p.preview_url ? `<button type="button" class="btn ghost sm" data-act="preview">${t("project.preview")}</button>` : ""}
        ${p.running ? `<button type="button" class="btn ghost sm" data-act="stop">${t("project.stop")}</button>` : ""}
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
      alert(t("project.noResponse"));
    }
  } catch {
    alert(t("project.previewFail"));
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
      alert(run.error || t("project.startFail"));
      await loadProjects();
      return;
    }
    if (run.url) {
      const title = proj?.name || t("project.defaultName");
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
    hideDocPreview();
    hideImagePreview();
    state.editor?.dispose();
    state.editor = null;
    showImagePreview(data);
    loadTree(state.treePath);
    return;
  }
  if (data.kind === "document") {
    if (!state.openTabs.includes(path)) state.openTabs.push(path);
    state.activeTab = path;
    renderTabs();
    renderMdToolbar();
    $("#app").classList.add("has-editor");
    hideMdPreview();
    hideImagePreview();
    hideAppPreview();
    state.editor?.dispose();
    state.editor = null;
    state.documentCache = state.documentCache || {};
    state.documentCache[path] = data;
    await showDocumentPreview(data);
    loadTree(state.treePath);
    return;
  }
  hideDocPreview();
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
      content = content.slice(0, 24000) + t("editor.truncated");
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
    label.textContent = t("agent.attachSel", { file: ctx.active_file || "" });
  } else if (ctx.active_file && state.autoAttach) {
    label.textContent = t("agent.attachFileShort", { name: ctx.active_file.split("/").pop() });
  } else {
    label.textContent = t("agent.attachFile");
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
  if (data.kind === "document") {
    state.documentCache = state.documentCache || {};
    state.documentCache[path] = data;
    if (state.activeTab === path) await showDocumentPreview(data);
    return;
  }
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

// ── 消息操作：重试 / 编辑重答（避免重复提问，可在原文基础上修改再答）──
function makeMsgActBtn(act, userIndex, iconName, titleKey) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "msg-act-btn";
  btn.dataset.act = act;
  btn.dataset.userIndex = String(userIndex);
  const label = t(titleKey);
  btn.title = label;
  btn.setAttribute("aria-label", label);
  setButtonIcon(btn, iconName, { size: 14 });
  return btn;
}

function appendUserActions(el, userIndex) {
  const acts = document.createElement("div");
  acts.className = "msg-actions";
  acts.append(
    makeMsgActBtn("edit", userIndex, "pencil", "chat.edit"),
    makeMsgActBtn("retry", userIndex, "refresh", "chat.retry"),
  );
  el.appendChild(acts);
}

function appendAssistantActions(el, userIndex) {
  if (!Number.isInteger(userIndex) || userIndex < 0) return;
  const acts = document.createElement("div");
  acts.className = "msg-actions";
  acts.append(makeMsgActBtn("retry", userIndex, "refresh", "chat.regenerate"));
  el.appendChild(acts);
}

let _retryPending = null;
let _retryRoleId = null;

function populateRetryOptionSelects() {
  const modeSel = $("#retry-opt-work-mode");
  if (modeSel) {
    const modes = state.workModes.length
      ? state.workModes
      : [{ id: "auto", label: "Auto" }];
    modeSel.innerHTML = modes
      .map((m) => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.label || m.id)}</option>`)
      .join("");
    modeSel.value = state.workMode || "auto";
  }
  _retryRoleId = state.roleId || "auto";
  renderRoleTreeMenus();
  const modelInput = $("#retry-opt-model");
  if (modelInput) {
    modelInput.value = state.info?.model?.model || "";
    modelInput.placeholder = state.info?.model?.model || "";
  }
}

function hideRetryOptions() {
  $("#retry-options-overlay")?.classList.add("hidden");
  _retryPending = null;
}

function showRetryOptions(pending) {
  _retryPending = pending;
  populateRetryOptionSelects();
  applyI18n($("#retry-options-overlay"));
  $("#retry-options-overlay")?.classList.remove("hidden");
  $("#retry-opt-work-mode")?.focus();
}

function readRetryOverrides() {
  const model = ($("#retry-opt-model")?.value || "").trim();
  return {
    workMode: $("#retry-opt-work-mode")?.value || state.workMode,
    roleId: _retryRoleId || state.roleId,
    model: model || undefined,
  };
}

// 截断到该用户回合之前，再以 text/images 重新发送，从而「就地重试 / 改后重答」。
async function resendFromUserTurn(userIndex, text, images, overrides = {}) {
  if (state.streaming) return;
  const convId = state.activeConversationId;
  if (!convId) return;
  const channel = state.mode === "chat" ? "chat" : "agent";
  try {
    const data = await api(`/api/chat/conversations/${convId}/truncate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_index: userIndex }),
    });
    await renderChatHistory(data.messages || []);
  } catch (e) {
    appendNotes([t("chat.retryFail", { msg: e.message || String(e) })]);
    return;
  }
  await sendMessage(text || "", channel, {
    images: images || [],
    workMode: overrides.workMode,
    roleId: overrides.roleId,
    model: overrides.model,
  });
}

function confirmRetryOptions() {
  const pending = _retryPending;
  if (!pending) return;
  const overrides = readRetryOverrides();
  hideRetryOptions();
  void resendFromUserTurn(
    pending.userIndex,
    pending.text,
    pending.images,
    overrides,
  );
}

function bindRetryOptions() {
  $("#retry-opt-cancel")?.addEventListener("click", hideRetryOptions);
  $("#retry-opt-confirm")?.addEventListener("click", confirmRetryOptions);
  $("#retry-options-overlay")?.addEventListener("click", (ev) => {
    if (ev.target.id === "retry-options-overlay") hideRetryOptions();
  });
  window.addEventListener("auc-locale-change", () => {
    if (!$("#retry-options-overlay")?.classList.contains("hidden")) {
      populateRetryOptionSelects();
    }
  });
}

// 把用户气泡切换为内联编辑器，保存后基于新文本重答。
function enterEditMode(userIndex, btn) {
  if (state.streaming) return;
  const bubble = btn.closest(".msg-user");
  if (!bubble || bubble.classList.contains("editing")) return;
  const turn = state.turns[userIndex] || { text: "", images: [] };
  const original = turn.text || "";
  bubble.classList.add("editing");
  const editor = document.createElement("div");
  editor.className = "msg-edit";
  const ta = document.createElement("textarea");
  ta.className = "msg-edit-input";
  ta.value = original;
  ta.rows = Math.min(10, Math.max(2, original.split("\n").length));
  const bar = document.createElement("div");
  bar.className = "msg-edit-bar";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "msg-edit-cancel";
  cancel.textContent = t("chat.editCancel");
  const save = document.createElement("button");
  save.type = "button";
  save.className = "msg-edit-save";
  save.textContent = t("chat.editSave");
  bar.append(cancel, save);
  editor.append(ta, bar);
  bubble.replaceChildren(editor);
  ta.focus();
  ta.setSelectionRange(original.length, original.length);
  const restore = () => {
    void renderChatHistory(state._lastHistory || []);
  };
  cancel.addEventListener("click", restore);
  save.addEventListener("click", () => {
    const next = ta.value.trim();
    if (!next) {
      restore();
      return;
    }
    restore();
    showRetryOptions({ userIndex, text: next, images: turn.images || [] });
  });
  ta.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
      ev.preventDefault();
      save.click();
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      restore();
    }
  });
}

function onMessageAction(ev) {
  const btn = ev.target.closest(".msg-act-btn");
  if (!btn) return;
  ev.preventDefault();
  ev.stopPropagation();
  if (state.streaming) return;
  const idx = Number(btn.dataset.userIndex);
  if (!Number.isInteger(idx) || idx < 0) return;
  const turn = state.turns[idx];
  if (!turn) return;
  if (btn.dataset.act === "edit") {
    enterEditMode(idx, btn);
  } else if (btn.dataset.act === "retry") {
    showRetryOptions({ userIndex: idx, text: turn.text, images: turn.images });
  }
}

function bindMessageActions() {
  for (const sel of ["#chat-messages", "#agent-messages"]) {
    $(sel)?.addEventListener("click", onMessageAction);
  }
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
  const userIndex = state.turns.length;
  state.turns[userIndex] = { text: text || "", images: images || [] };
  const el = buildUserMessageEl(text, images);
  appendUserActions(el, userIndex);
  el.dataset.userIndex = String(userIndex);
  targetMessages().appendChild(el);
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

function formatEventTime(ts) {
  if (ts == null || ts === "") return "";
  try {
    const ms = typeof ts === "number" ? (ts < 1e12 ? ts * 1000 : ts) : Date.parse(ts);
    if (!Number.isFinite(ms)) return "";
    const d = new Date(ms);
    const h = String(d.getHours()).padStart(2, "0");
    const m = String(d.getMinutes()).padStart(2, "0");
    const s = String(d.getSeconds()).padStart(2, "0");
    const f = String(d.getMilliseconds()).padStart(3, "0");
    return `${h}:${m}:${s}.${f}`;
  } catch {
    return "";
  }
}

function logTimeHtml(ts) {
  const s = formatEventTime(ts);
  return s ? `<span class="log-time">[${escapeHtml(s)}]</span>` : "";
}

let _richUpgradeBound = false;

async function renderChatHistory(messages) {
  lastRunModel = null;
  state._lastHistory = messages || [];
  // 富渲染依赖（CDN）异步加载：若渲染历史时尚未就绪，加载完成后自动重渲一次升级。
  if (!_richUpgradeBound && state._lastHistory.length) {
    _richUpgradeBound = true;
    richRenderersReady.then((ready) => {
      if (ready && (ready.marked || ready.mermaid) && state._lastHistory?.length) {
        void renderChatHistory(state._lastHistory);
      }
    });
  }
  const panels = ["#chat-messages", "#agent-messages"];
  for (const sel of panels) {
    const root = $(sel);
    if (root) root.innerHTML = "";
  }
  state.turns = [];
  let userIdx = -1;
  for (const m of messages || []) {
    if (m.role === "user") {
      userIdx += 1;
      state.turns[userIdx] = { text: m.content || "", images: m.images || [] };
      const el = buildUserMessageEl(m.content, m.images);
      appendUserActions(el, userIdx);
      el.dataset.userIndex = String(userIdx);
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
        appendAssistantActions(el, userIdx);
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
    list.innerHTML = `<div class="conv-empty">${escapeHtml(t("conv.empty"))}</div>`;
    return;
  }
  for (const c of state.conversations) {
    const row = document.createElement("div");
    row.className = "conv-item" + (c.id === state.activeConversationId ? " active" : "");
    row.dataset.id = c.id;
    const metaParts = [
      `${formatConvTime(c.updated_at)} · ${t("conv.turns", { n: c.message_count || 0 })}`,
    ];
    const usageText = usageLabel(c.usage);
    if (usageText) metaParts.push(usageText);
    const meta = metaParts.join(" · ");
    row.innerHTML = `
      <div class="conv-body">
        <div class="conv-title">${escapeHtml(c.title || t("conv.newTitle"))}</div>
        <div class="conv-meta">${escapeHtml(meta)}</div>
      </div>
      <button type="button" class="conv-del" title="${escapeHtml(t("conv.del"))}">${icon("trash", { size: 14 })}</button>`;
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
let lastRunModel = null;
const diagramRepairMeta = new WeakMap();

function messageTheme() {
  return isColorThemeDark(state.colorTheme) ? "dark" : "light";
}

function beginAssistant() {
  streamText = "";
  state._todoCardEl = null;
  streamEl = document.createElement("div");
  streamEl.className = "msg msg-assistant";
  streamEl.innerHTML = '<span class="marker">◆</span><span class="msg-stream"></span>';
  targetMessages().appendChild(streamEl);
}

// 顶栏 model-pill 与本次 Run 使用的模型保持一致。
function syncModelPill(model) {
  if (!model && !state.info?.model?.model) return;
  updateModelPillDisplay(model);
}

// 智能路由策略 → 标签（与后端 auc/model/routing.py 对齐）。
const ROUTING_STRATEGY_LABELS = {
  cost_optimized: "成本优先",
  balanced: "均衡",
  quality_first: "质量优先",
  latency_critical: "低延迟优先",
};

function parseAutoModel(model) {
  const head = String(model || "").trim().toLowerCase();
  if (head !== "auto" && !head.startsWith("auto:")) return null;
  const parts = head.split(":");
  const strategy = parts[1]?.trim() || "cost_optimized";
  return ROUTING_STRATEGY_LABELS[strategy] ? strategy : "cost_optimized";
}

function modelDisplay(model) {
  const strategy = parseAutoModel(model);
  if (!strategy) return model;
  const label = t(`model.autoStrategy.${strategy}`) || ROUTING_STRATEGY_LABELS[strategy];
  return `${t("model.smartRouting")} · ${label}`;
}

// 把模型信息渲染成「按钮」样式的徽标；点击可打开模型设置。
function appendModelNote({ variant, icon, label, timestamp, title }) {
  const el = document.createElement("div");
  el.className = "msg msg-model-note" + (variant ? ` ${variant}` : "");
  el.innerHTML = logTimeHtml(timestamp ?? Date.now() / 1000);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "model-note-btn";
  if (title) btn.title = title;
  btn.innerHTML = `<span class="model-note-icon">${icon}</span><span class="model-note-text">${escapeHtml(label)}</span>`;
  btn.addEventListener("click", () => void openModelPlaza());
  el.appendChild(btn);
  targetMessages().appendChild(el);
  return el;
}

// 运行时显示本次使用的大模型；模型相对上一次 Run 变化时高亮「切换」。
function renderRunModel(model, timestamp) {
  if (!model) return;
  const switched = !!lastRunModel && lastRunModel !== model;
  const label = switched
    ? t("model.switched", { from: modelDisplay(lastRunModel), to: modelDisplay(model) })
    : t("model.runningModel", { model: modelDisplay(model) });
  appendModelNote({
    variant: switched ? "switched" : "",
    icon: switched ? "⇄" : "⬡",
    label,
    timestamp,
    title: t("model.openSettingsTip"),
  });
  lastRunModel = model;
  syncModelPill(model);
}

// 智能路由：网关实际选出的模型；source=local 表示网关无 auto、由本地选型。
function renderResolvedModel(payload, timestamp) {
  const resolved = payload?.resolved;
  if (!resolved) return;
  const local = payload?.source === "local";
  appendModelNote({
    variant: "resolved",
    icon: local ? "⚙" : "⟿",
    label: local
      ? t("model.resolvedLocal", { model: resolved })
      : t("model.resolvedAs", { model: resolved }),
    timestamp,
    title: local ? t("model.localRoutingTip") : t("model.openSettingsTip"),
  });
  scrollMessages();
}

// token 用量以 K（千）为单位、保留 1 位小数显示。
const BILLED_COST_MULTIPLIER = 1.5;

function fmtTokK(n) {
  return `${((Number(n) || 0) / 1000).toFixed(1)}K`;
}

function billedCostUsd(actual) {
  return (Number(actual) || 0) * BILLED_COST_MULTIPLIER;
}

function fmtCostUsd(actual) {
  return billedCostUsd(actual).toFixed(4);
}

function usageLabel(usage) {
  if (!usage || !usage.total_tokens) return "";
  return t("conv.usage", {
    tokens: fmtTokK(usage.total_tokens),
    cost: fmtCostUsd(usage.cost_usd),
  });
}

function updateConversationUsageInState(convId, usage) {
  if (!convId || !usage) return;
  const row = state.conversations.find((c) => c.id === convId);
  if (row) row.usage = usage;
  if (state.info?.conversation && state.activeConversationId === convId) {
    state.info.conversation.usage = usage;
  }
}

function renderActiveConversationUsage(usage = state.info?.conversation?.usage) {
  const el = $("#agent-usage");
  if (!el) return;
  if (!usage || !usage.total_tokens) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = t("usage.cumulative", {
    tokens: fmtTokK(usage.total_tokens),
    cost: fmtCostUsd(usage.cost_usd),
  });
}

function renderUsage(usage) {
  if (!usage || !usage.total_tokens) return;
  const el = document.createElement("div");
  el.className = "msg msg-usage";
  const cost = usage.cost_usd
    ? ` · $${fmtCostUsd(usage.cost_usd)}`
    : "";
  const cumulative = state.info?.conversation?.usage;
  const cumulativeLine =
    cumulative && cumulative.total_tokens
      ? ` · ${t("usage.cumulative", {
          tokens: fmtTokK(cumulative.total_tokens),
          cost: fmtCostUsd(cumulative.cost_usd),
        })}`
      : "";
  const over = usage.budget_exceeded
    ? ` · ${escapeHtml(t("usage.budgetExceeded"))}`
    : "";
  el.innerHTML =
    `<span>⛁ ↑${fmtTokK(usage.prompt_tokens)} ↓${fmtTokK(usage.completion_tokens)} ` +
    `Σ${fmtTokK(usage.total_tokens)} tok${cost}${cumulativeLine}${over}</span>`;
  targetMessages().appendChild(el);
  scrollMessages();
}

const TODO_STATUS_ICON = {
  completed: "✓",
  in_progress: "◐",
  pending: "○",
  cancelled: "✗",
};

function renderTodos(todos, timestamp) {
  const list = Array.isArray(todos) ? todos : [];
  const done = list.filter((t) => t.status === "completed").length;
  const card =
    state._todoCardEl && state._todoCardEl.isConnected
      ? state._todoCardEl
      : (() => {
          const el = document.createElement("div");
          el.className = "msg msg-todos";
          targetMessages().appendChild(el);
          state._todoCardEl = el;
          return el;
        })();
  const time = logTimeHtml(timestamp ?? Date.now() / 1000);
  const rows = list
    .map((todo) => {
      const status = TODO_STATUS_ICON[todo.status] ? todo.status : "pending";
      const icon = TODO_STATUS_ICON[status];
      return `<li class="todo-item todo-${status}"><span class="todo-icon">${icon}</span><span class="todo-text">${escapeHtml(
        todo.content || "",
      )}</span></li>`;
    })
    .join("");
  card.innerHTML =
    `<div class="todos-head">${time}<span>${escapeHtml(
      t("todos.title"),
    )}</span><span class="todos-progress">${done}/${list.length}</span></div>` +
    `<ul class="todos-list">${rows}</ul>`;
  scrollMessages();
}

function renderSubagent(payload, done, timestamp) {
  const p = payload || {};
  const el = document.createElement("div");
  el.className = "msg msg-subagent";
  const time = logTimeHtml(timestamp ?? Date.now() / 1000);
  const kind = escapeHtml(p.kind || "");
  if (done) {
    const files = Array.isArray(p.changed_files) ? p.changed_files.length : 0;
    const extra = files ? ` · ${files} ${t("subagent.files")}` : "";
    el.innerHTML = `<span>${time}⎿ ${t("subagent.done")} [${kind}] · ${escapeHtml(
      p.status || "",
    )}${extra}</span>`;
  } else {
    const task = escapeHtml((p.task || "").slice(0, 80));
    el.innerHTML = `<span>${time}⌥ ${t("subagent.start")} [${kind}] ${task}</span>`;
  }
  targetMessages().appendChild(el);
  scrollMessages();
}

function renderReceipt(path, timestamp) {
  const card = document.createElement("div");
  card.className = "msg msg-receipt";
  const time = logTimeHtml(timestamp ?? Date.now() / 1000);
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.innerHTML = `${time}<span>📄 ${escapeHtml(t("receipt.title"))}</span>`;
  details.appendChild(summary);
  const body = document.createElement("div");
  body.className = "receipt-body";
  body.textContent = t("receipt.loading");
  details.appendChild(body);
  card.appendChild(details);
  targetMessages().appendChild(card);
  scrollMessages();

  fetch("/api/receipt")
    .then((r) => (r.ok ? r.json() : Promise.reject(r)))
    .then((data) => {
      body.replaceChildren(
        buildMessageContent(data.markdown || "", { theme: messageTheme() }),
      );
    })
    .catch(() => {
      body.textContent = t("receipt.error");
    });
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
          data.method === "agent" ? t("diagram.fixedAgent") : t("diagram.fixedAuto");
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

function appendTool(name, args, summary, isError, timestamp) {
  const el = document.createElement("div");
  el.className = "msg msg-tool";
  const label = formatTool(name, args);
  const time = logTimeHtml(timestamp ?? Date.now() / 1000);
  el.innerHTML = `<div>${time}● ${escapeHtml(label)}</div>`;
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
  const extra = approvalQueue.length ? t("approval.pending", { n: approvalQueue.length }) : "";
  if (summary) {
    summary.textContent =
      (payload.risk_summary || t("approval.request", { tool: payload.tool || "L3" })) + extra;
  }
  if (urlEl) {
    const args = payload.arguments || {};
    const url = args.url || args.command || args.path || "";
    const save = args.save_path || "";
    urlEl.textContent = url + (save ? `\n${t("approval.saveTo", { path: save })}` : "");
  }
  renderApprovalDiff(payload);
  overlay.classList.remove("hidden");
}

function renderApprovalDiff(payload) {
  const wrap = $("#approval-diff");
  const body = $("#approval-diff-body");
  const stat = $("#approval-diff-stat");
  if (!wrap || !body) return;
  const diff = payload.diff_text || "";
  const isWrite = payload.tool === "write_file";
  // 仅对 write_file 的 unified diff 渲染逐行高亮；命令/路径已在 url 区展示。
  if (!diff || !isWrite || !/^(---|\+\+\+|@@|[+\- ])/m.test(diff)) {
    wrap.classList.add("hidden");
    body.innerHTML = "";
    if (stat) stat.textContent = "";
    return;
  }
  let added = 0;
  let removed = 0;
  const html = diff
    .split("\n")
    .map((line) => {
      let cls = "diff-ctx";
      if (line.startsWith("+++") || line.startsWith("---")) {
        cls = "diff-meta";
      } else if (line.startsWith("@@")) {
        cls = "diff-hunk";
      } else if (line.startsWith("+")) {
        cls = "diff-add";
        added += 1;
      } else if (line.startsWith("-")) {
        cls = "diff-del";
        removed += 1;
      }
      return `<span class="${cls}">${escapeHtml(line)}</span>`;
    })
    .join("\n");
  body.innerHTML = html;
  if (stat) stat.textContent = `+${added} −${removed}`;
  wrap.classList.remove("hidden");
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
        reason: approved ? "" : t("approval.deniedReason"),
      }),
    });
    appendNotes([approved ? t("approval.approvedNote") : t("approval.rejectedNote")]);
  } catch (e) {
    appendNotes([t("approval.failedNote", { msg: e.message })]);
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

function appendLogNote(text, ts) {
  const el = document.createElement("div");
  el.className = "msg msg-note";
  const time = logTimeHtml(ts);
  el.innerHTML = `${time}<span>✗ ${escapeHtml(text)}</span>`;
  targetMessages().appendChild(el);
}

function insertTerminalToPrompt(text, { kind = "error", auto = false } = {}) {
  const input = $("#prompt");
  if (!input) return;
  const block = text.trim();
  if (!block) return;
  const wrapped = `\n\n--- 终端输出 ---\n${block}\n--- end ---\n`;
  const prefix =
    kind === "error"
      ? "请帮我分析以下终端报错："
      : "请根据以下终端输出协助我：";
  if (input.value.trim()) {
    input.value = `${input.value.trim()}${wrapped}`;
  } else {
    input.value = `${prefix}\n${wrapped.trim()}`;
  }
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.focus();
  if (state.mode !== "code") setMode("code");
  if (!auto) {
    $("#agent-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
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

async function sendMessage(text, channel = "agent", opts = {}) {
  // opts.images：重试 / 编辑重答时显式传入历史图片，且不消费输入框附件。
  const explicitImages = Array.isArray(opts.images) ? opts.images : null;
  const images = explicitImages ? [...explicitImages] : [...(state.attachments[channel] || [])];
  if (!explicitImages && !chatHasInput(text, images, channel)) return;
  if (state.streaming) return;
  const streamConversationId = state.activeConversationId;
  state.streaming = true;
  setButtons(true);
  renderAgentProfile();
  const payloadImages = images.map(({ mime_type, data_base64, name }) => ({
    mime_type, data_base64, name,
  }));
  appendUser(text, payloadImages);
  if (!explicitImages) {
    state.attachments[channel] = [];
    renderAttachStrip(channel);
  }

  const controller = new AbortController();
  state.abort = controller;

  try {
    if (channel === "agent") {
      try {
        await syncActiveFileToServer();
      } catch (syncErr) {
        appendNotes([t("chat.saveSkip", { msg: syncErr.message })]);
      }
    }
    const context = channel === "agent" ? getEditorContext() : null;
    const workMode = opts.workMode ?? state.workMode;
    const roleId = opts.roleId ?? state.roleId;
    const modelOverride = opts.model;
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text || "",
        images: payloadImages,
        context,
        work_mode: workMode,
        role_id: roleId,
        role_locale: getLocale(),
        skill_mode: opts.skillMode ?? state.skillMode,
        skill_ids: opts.skillIds ?? state.skillPinned,
        approval_mode: opts.approvalMode ?? state.approvalMode,
        model: modelOverride,
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
        if (!doneEl.querySelector(".msg-actions")) {
          appendAssistantActions(doneEl, state.turns.length - 1);
        }
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
    const time = logTimeHtml(ev.timestamp);
    el.innerHTML = `${time}<span>✗ ${escapeHtml(ev.payload?.message || t("chat.unknownError"))}</span>`;
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
    renderRunModel(ev.payload?.model, ev.timestamp);
    beginAssistant();
    return;
  }
  if (ev.type === "model_delta") {
    if (ev.payload?.delta) appendDelta(ev.payload.delta);
    return;
  }
  if (ev.type === "model_resolved") {
    renderResolvedModel(ev.payload, ev.timestamp);
    return;
  }
  if (ev.type === "done") {
    clearTimeout(renderTimer);
    if (streamEl && streamText) flushMessageRender();
    if (ev.payload?.status !== "completed" && ev.payload?.error) {
      appendLogNote(ev.payload.error, ev.timestamp);
    } else if (ev.payload?.status === "completed" && !streamText && !streamEl) {
      const out = ev.payload?.output;
      if (out) appendDelta(out);
    }
    if (ev.payload?.usage) {
      updateConversationUsageInState(ev.payload.conversation_id, ev.payload.usage);
      renderActiveConversationUsage(ev.payload.usage);
    }
    renderUsage(state._lastUsage);
    state._lastUsage = null;
    return;
  }
  if (ev.type === "todos_updated") {
    renderTodos(ev.payload?.todos || [], ev.timestamp);
    return;
  }
  if (ev.type === "usage_updated") {
    state._lastUsage = ev.payload || null;
    return;
  }
  if (ev.type === "receipt_ready") {
    renderReceipt(ev.payload?.path, ev.timestamp);
    return;
  }
  if (ev.type === "subagent_start") {
    renderSubagent(ev.payload, false, ev.timestamp);
    return;
  }
  if (ev.type === "subagent_end") {
    renderSubagent(ev.payload, true, ev.timestamp);
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
      ev.timestamp,
    );
    state._pendingTool = null;
    if (
      !ev.payload?.is_error
      && ["define_role", "update_role", "switch_role"].includes(toolName)
    ) {
      loadInfo()
        .then(() => {
  populateRoleSelects();
  bindRoleTreeSelects();
          renderAgentProfile();
        })
        .catch(() => {});
    }
    return;
  }
  if (ev.type === "run_end" && ev.payload?.status === "cancelled") {
    const el = document.createElement("div");
    el.className = "msg msg-note";
    const time = logTimeHtml(ev.timestamp);
    el.innerHTML = `${time}<span>${escapeHtml(t("chat.cancelled"))}</span>`;
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
  updateAgentStatus();
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
      alert(t("chat.imageTooBig", { name: file.name }));
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
  input.value = (input.value ? input.value + " " : "") + t("agent.insertFileToken");
  input.focus();
});
$("#btn-insert-sel")?.addEventListener("click", () => {
  const input = $("#prompt");
  if (!input) return;
  input.value = (input.value ? input.value + " " : "") + t("agent.insertSelToken");
  input.focus();
});

function openReviewDialog() {
  const overlay = $("#review-overlay");
  if (!overlay) return;
  const fileRadio = overlay.querySelector('input[value="file"]');
  if (fileRadio) fileRadio.disabled = !state.activeTab;
  if (fileRadio && !state.activeTab) {
    const diff = overlay.querySelector('input[value="diff"]');
    if (diff) diff.checked = true;
  }
  overlay.classList.remove("hidden");
}

function hideReviewDialog() {
  $("#review-overlay")?.classList.add("hidden");
}

async function runReview() {
  if (state.streaming) return;
  const scope =
    document.querySelector('input[name="review-scope"]:checked')?.value || "file";
  const body = {};
  let label = "";
  if (scope === "file") {
    if (!state.activeTab) {
      appendNotes([t("review.noFile")]);
      return;
    }
    body.path = state.activeTab;
    label = state.activeTab;
  } else if (scope === "staged") {
    body.diff = true;
    body.staged = true;
    label = t("review.scopeStaged");
  } else {
    body.diff = true;
    label = t("review.scopeDiff");
  }
  hideReviewDialog();

  state.streaming = true;
  setButtons(true);
  const note = document.createElement("div");
  note.className = "msg msg-note";
  note.textContent = `🔎 ${t("review.running", { target: label })}`;
  targetMessages().appendChild(note);
  scrollMessages();

  const controller = new AbortController();
  state.abort = controller;
  try {
    const res = await fetch("/api/chat/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() || "";
      for (const chunk of parts) {
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        handleReviewEvent(JSON.parse(line.slice(6)));
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") appendNotes([`✗ ${e.message}`]);
  } finally {
    state.streaming = false;
    state.abort = null;
    setButtons(false);
  }
}

function handleReviewEvent(ev) {
  if (ev.type === "error") {
    appendNotes([`✗ ${ev.payload?.message || "review error"}`]);
    return;
  }
  if (ev.type === "review_pass") {
    const p = ev.payload || {};
    const el = document.createElement("div");
    el.className = "msg msg-tool";
    el.innerHTML = `<div>${logTimeHtml(Date.now() / 1000)}● ${escapeHtml(
      t("review.passDone", {
        index: p.index,
        total: p.total,
        label: p.label,
        count: p.count,
      }),
    )}</div>`;
    targetMessages().appendChild(el);
    scrollMessages();
    return;
  }
  if (ev.type === "review_report") {
    const md = ev.payload?.markdown || "";
    const el = document.createElement("div");
    el.className = "msg msg-assistant";
    const stream = document.createElement("span");
    stream.className = "msg-stream";
    stream.replaceChildren(buildMessageContent(md, { theme: messageTheme() }));
    el.appendChild(stream);
    targetMessages().appendChild(el);
    const todos = ev.payload?.todos || [];
    if (todos.length) {
      state._todoCardEl = null;
      renderTodos(todos, Date.now() / 1000);
    }
    scrollMessages();
    return;
  }
}

$("#btn-review")?.addEventListener("click", openReviewDialog);
$("#review-cancel")?.addEventListener("click", hideReviewDialog);
$("#review-run")?.addEventListener("click", () => void runReview());
$("#review-overlay")?.addEventListener("click", (ev) => {
  if (ev.target.id === "review-overlay") hideReviewDialog();
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
async function refreshUiLocale() {
  applyI18n();
  await loadInfo().catch(() => {});
  updateContextBar();
  populateWorkModeSelects();
  populateApprovalSelects();
  populateRoleSelects();
  bindRoleTreeSelects();
  updateRoleTriggers();
  void loadProjects();
  void loadConversations();
  void loadTree(state.treePath);
  if (state.activeTab && state.documentCache?.[state.activeTab]) {
    void showDocumentPreview(state.documentCache[state.activeTab]);
  }
}

async function boot() {
  applyI18n();
  updateRoleTriggers();
  $("#lang-toggle")?.addEventListener("click", () => toggleLocale());
  window.addEventListener("auc-locale-change", refreshUiLocale);
  initThemes();
  initSidebarChrome();
  initTerminalPanel();
  window.addEventListener("auc-terminal-to-agent", (ev) => {
    const detail = ev.detail || {};
    insertTerminalToPrompt(detail.text, {
      kind: detail.kind || "error",
      auto: Boolean(detail.auto),
    });
  });
  bindUpdateBanner();
  bindModelSettings();
  bindModelPlaza();
  bindRolePlaza();
  bindSkillPlaza();
  bindChoicePillKeyboard();
  bindRoleTreeSelects();
  bindMessageActions();
  bindRetryOptions();
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
  scheduleReleaseRecheck();
}

boot().catch((e) => {
  document.body.innerHTML = `<pre style="padding:2rem;color:#c00">${escapeHtml(t("boot.fail", { msg: e.message }))}</pre>`;
});
