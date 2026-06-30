/**
 * 助手消息渲染：Mermaid 全类型图表 / Markdown / 代码块
 */

// 富渲染依赖（mermaid / marked / dompurify）按需从 CDN 动态加载。
// 关键：绝不能用顶层静态 import，否则 CDN 不可达（离线/内网）时整个模块图加载失败，
// 进而 app.js 无法启动、页面空白。改为后台动态加载，失败则降级为纯文本/源码展示。
let mermaid = null;
let marked = null;
let DOMPurify = null;

let mermaidReady = false;
let markdownReady = false;
let renderCounter = 0;

// 每个依赖按顺序尝试多个 CDN 镜像（jsdelivr 在部分网络/中国大陆常不稳定，
// 故附带 fastly / esm.sh / unpkg 等备选），任一成功即用。
const CDN_SOURCES = {
  mermaid: [
    "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs",
    "https://fastly.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs",
    "https://esm.sh/mermaid@11",
    "https://unpkg.com/mermaid@11/dist/mermaid.esm.min.mjs",
  ],
  marked: [
    "https://cdn.jsdelivr.net/npm/marked@15/+esm",
    "https://fastly.jsdelivr.net/npm/marked@15/+esm",
    "https://esm.sh/marked@15",
  ],
  dompurify: [
    "https://cdn.jsdelivr.net/npm/dompurify@3/+esm",
    "https://fastly.jsdelivr.net/npm/dompurify@3/+esm",
    "https://esm.sh/dompurify@3",
  ],
};

async function loadFromMirrors(urls) {
  for (const url of urls) {
    try {
      return await import(/* @vite-ignore */ url);
    } catch {
      // 试下一个镜像
    }
  }
  return null;
}

/** 后台加载富渲染依赖；任一失败都不影响 UI 启动，只降级渲染。 */
export const richRenderersReady = (async () => {
  const [mmd, mk, dp] = await Promise.all([
    loadFromMirrors(CDN_SOURCES.mermaid),
    loadFromMirrors(CDN_SOURCES.marked),
    loadFromMirrors(CDN_SOURCES.dompurify),
  ]);
  if (mmd) mermaid = mmd.default || mmd;
  if (mk) marked = mk.marked || mk.default || mk;
  if (dp) DOMPurify = dp.default || dp;
  const failed = [
    !mermaid && "mermaid",
    !marked && "marked",
    !DOMPurify && "dompurify",
  ].filter(Boolean);
  if (failed.length) {
    console.warn(
      `[AuC] 富渲染依赖加载失败（${failed.join(", ")}）：Markdown/图表将降级显示。` +
        `如处于离线/内网环境，请配置可达的 CDN 或本地静态资源。`,
    );
  }
  return { mermaid: !!mermaid, marked: !!marked, dompurify: !!DOMPurify };
})();

/** fence 语言标记 → 图表类型 ID */
const FENCE_LANG_TO_TYPE = {
  mermaid: "mermaid",
  flowchart: "flowchart",
  graph: "flowchart",
  sequencediagram: "sequence",
  sequence: "sequence",
  classdiagram: "class",
  class: "class",
  statediagram: "state",
  state: "state",
  erdiagram: "er",
  er: "er",
  gantt: "gantt",
  pie: "pie",
  journey: "journey",
  gitgraph: "git",
  mindmap: "mindmap",
  timeline: "timeline",
  quadrantchart: "quadrant",
  requirementdiagram: "requirement",
  c4: "c4",
  c4context: "c4",
  c4container: "c4",
  c4component: "c4",
  c4dynamic: "c4",
  c4deployment: "c4",
  block: "block",
  "block-beta": "block",
  kanban: "kanban",
  sankey: "sankey",
  "sankey-beta": "sankey",
  xychart: "xychart",
  "xychart-beta": "xychart",
  architecture: "architecture",
  "architecture-beta": "architecture",
  packet: "packet",
  "packet-beta": "packet",
  zenuml: "zenuml",
};

const MERMAID_LANGS = new Set(Object.keys(FENCE_LANG_TO_TYPE));

/** 从源码首行识别 Mermaid 图表类型 */
const MERMAID_DETECTORS = [
  { re: /^(flowchart|graph)\b/i, type: "flowchart" },
  { re: /^sequenceDiagram\b/i, type: "sequence" },
  { re: /^classDiagram\b/i, type: "class" },
  { re: /^stateDiagram(-v2)?\b/i, type: "state" },
  { re: /^erDiagram\b/i, type: "er" },
  { re: /^gantt\b/i, type: "gantt" },
  { re: /^pie\b/i, type: "pie" },
  { re: /^journey\b/i, type: "journey" },
  { re: /^gitGraph\b/i, type: "git" },
  { re: /^mindmap\b/i, type: "mindmap" },
  { re: /^timeline\b/i, type: "timeline" },
  { re: /^quadrantChart\b/i, type: "quadrant" },
  { re: /^requirementDiagram\b/i, type: "requirement" },
  { re: /^C4(Context|Container|Component|Dynamic|Deployment)\b/i, type: "c4" },
  { re: /^(block-beta|block)\b/i, type: "block" },
  { re: /^kanban\b/i, type: "kanban" },
  { re: /^(sankey-beta|sankey)\b/i, type: "sankey" },
  { re: /^(xychart-beta|xyChart-beta|xychart)\b/i, type: "xychart" },
  { re: /^(architecture-beta|architecture)\b/i, type: "architecture" },
  { re: /^(packet-beta|packet)\b/i, type: "packet" },
  { re: /^zenuml\b/i, type: "zenuml" },
];

const DIAGRAM_LABELS = {
  flowchart: "流程图",
  sequence: "时序图",
  class: "类图",
  state: "状态图",
  er: "ER 图",
  gantt: "甘特图",
  pie: "饼图",
  journey: "用户旅程图",
  git: "Git 图",
  mindmap: "思维导图",
  timeline: "时间线",
  quadrant: "象限图",
  requirement: "需求图",
  c4: "C4 架构图",
  block: "块图",
  kanban: "看板图",
  sankey: "桑基图",
  xychart: "XY 图表",
  architecture: "架构图",
  packet: "数据包图",
  zenuml: "ZenUML 图",
  mermaid: "Mermaid 图表",
};

export function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function detectMermaidDiagramType(code, fenceLang = "") {
  const lang = (fenceLang || "").trim().toLowerCase();
  if (lang && FENCE_LANG_TO_TYPE[lang]) {
    const mapped = FENCE_LANG_TO_TYPE[lang];
    if (mapped !== "mermaid") return mapped;
  }
  for (const line of String(code).split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("%%")) continue;
    for (const { re, type } of MERMAID_DETECTORS) {
      if (re.test(trimmed)) return type;
    }
    break;
  }
  return "mermaid";
}

export function getDiagramLabel(typeId) {
  return DIAGRAM_LABELS[typeId] || DIAGRAM_LABELS.mermaid;
}

function isMermaidBlock(lang, code) {
  const l = (lang || "").trim().toLowerCase();
  if (MERMAID_LANGS.has(l)) return true;
  if (l && l !== "text" && l !== "txt") return false;
  for (const line of String(code).split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("%%")) continue;
    return MERMAID_DETECTORS.some(({ re }) => re.test(trimmed));
  }
  return false;
}

export function parseFencedBlocks(text) {
  const parts = [];
  const segments = String(text).split("```");
  for (let i = 0; i < segments.length; i++) {
    if (i % 2 === 0) {
      if (segments[i]) parts.push({ type: "text", content: segments[i] });
      continue;
    }
    const body = segments[i];
    const nl = body.indexOf("\n");
    const lang = (nl >= 0 ? body.slice(0, nl) : body).trim().toLowerCase();
    const code = (nl >= 0 ? body.slice(nl + 1) : "").replace(/\n$/, "");
    const complete = i < segments.length - 1;
    if (isMermaidBlock(lang, code)) {
      const diagramType = detectMermaidDiagramType(code, lang);
      parts.push({ type: "mermaid", content: code, complete, lang, diagramType });
    } else {
      parts.push({ type: "code", lang, content: code, complete });
    }
  }
  return parts;
}

/** gantt title/section/任务名中的特殊字符需加引号 */
const GANTT_SPECIAL_RE = /[:：;#+→/\\]|[^\x00-\x7f]/;
const GANTT_CONFIG_PREFIXES = [
  "title ",
  "section ",
  "dateformat",
  "axisformat",
  "excludes",
  "includes",
  "todaymarker",
  "tickinterval",
  "weekday",
  "weekend",
  "topaxis",
];

function needsGanttQuote(text) {
  const t = String(text || "").trim();
  if (!t) return false;
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
    return false;
  }
  return GANTT_SPECIAL_RE.test(t);
}

function quoteGanttText(text) {
  return String(text).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function isGanttConfigLine(stripped) {
  const lower = stripped.toLowerCase();
  if (lower.startsWith("%%")) return true;
  return GANTT_CONFIG_PREFIXES.some((p) => lower.startsWith(p));
}

function tryLocalGanttFix(code) {
  if (!/^\s*gantt\b/im.test(code)) return code;
  return code.split("\n").map((line) => {
    const stripped = line.trimStart();
    const indent = line.slice(0, line.length - stripped.length);
    const lower = stripped.toLowerCase();

    if (lower.startsWith("title ")) {
      const title = stripped.slice(6).trim();
      if (needsGanttQuote(title)) {
        return `${indent}title "${quoteGanttText(title)}"`;
      }
      return line;
    }
    if (lower.startsWith("section ")) {
      const name = stripped.slice(8).trim();
      if (needsGanttQuote(name)) {
        return `${indent}section "${quoteGanttText(name)}"`;
      }
      return line;
    }
    if (lower.startsWith("axisformat")) {
      const parts = stripped.split(/\s+/, 2);
      if (parts.length === 2) {
        const fmt = parts[1].trim();
        if (!((fmt.startsWith('"') && fmt.endsWith('"')) || (fmt.startsWith("'") && fmt.endsWith("'")))) {
          return `${indent}axisFormat "${quoteGanttText(fmt)}"`;
        }
      }
      return line;
    }
    if (stripped && !isGanttConfigLine(stripped) && stripped.includes(":")) {
      const m = line.match(/^(\s*)(.+?)\s+:(.+)$/);
      if (m) {
        const name = m[2].trim();
        const meta = m[3];
        if (needsGanttQuote(name)) {
          return `${indent}"${quoteGanttText(name)}" :${meta}`;
        }
      }
    }
    return line;
  }).join("\n");
}

/** 启发式修复 subgraph / 节点标签 / gantt 中的中文与特殊字符 */
export function tryLocalMermaidFix(code) {
  if (/^\s*gantt\b/im.test(code)) {
    const ganttFixed = tryLocalGanttFix(code);
    if (ganttFixed !== code) return ganttFixed;
  }
  let fixed = code;
  fixed = fixed.replace(/^(\s*subgraph\s+)(.+)$/gm, (line, prefix, title) => {
    const t = title.trim();
    if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
      return line;
    }
    if (/[\u4e00-\u9fff：:（）()/\s]/.test(t) || /[^\x00-\x7f]/.test(t)) {
      return `${prefix}"${t}"`;
    }
    return line;
  });
  fixed = fixed.replace(/(\b[\w][\w-]*\s*)\[([^\]"]+)\]/g, (m, id, label) => {
    const t = label.trim();
    if (/[\u4e00-\u9fff：:（）()/\s]/.test(t) || /[^\x00-\x7f]/.test(t)) {
      return `${id}["${t.replace(/"/g, '\\"')}"]`;
    }
    return m;
  });
  return fixed;
}

export function replaceMermaidInText(text, oldCode, newCode) {
  const oldTrim = oldCode.trim();
  const newTrim = newCode.trim();
  return String(text).replace(/```mermaid\s*\n([\s\S]*?)\n```/gi, (block, code) => {
    if (code.trim() === oldTrim) {
      return "```mermaid\n" + newTrim + "\n```";
    }
    return block;
  });
}

function initMarkdown() {
  if (markdownReady || !marked) return;
  marked.setOptions({
    gfm: true,
    breaks: true,
    headerIds: false,
    mangle: false,
  });
  markdownReady = true;
}

/** CDN 不可达时的纯文本降级：转义 + 换行保留，保证内容可读。 */
function renderMarkdownFallback(src) {
  return `<div class="msg-md-plain">${escapeHtml(src).replace(/\n/g, "<br>")}</div>`;
}

export function renderMarkdown(text) {
  const src = String(text || "");
  if (!src.trim()) return "";
  if (!marked) return renderMarkdownFallback(src);
  initMarkdown();
  const html = marked.parse(src, { async: false });
  if (!DOMPurify) return renderMarkdownFallback(src);
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    ADD_ATTR: ["target", "rel"],
  });
}

export function initDiagrams(theme = "dark") {
  if (mermaidReady || !mermaid) return;
  mermaid.initialize({
    startOnLoad: false,
    theme: theme === "light" ? "default" : "dark",
    securityLevel: "strict",
    fontFamily: "Inter, Segoe UI, system-ui, sans-serif",
    flowchart: { curve: "basis", htmlLabels: true },
  });
  mermaidReady = true;
}

function createDiagramLabel(typeId) {
  const wrap = document.createElement("span");
  wrap.className = "diagram-label-wrap";
  const label = document.createElement("span");
  label.className = "diagram-label";
  label.textContent = getDiagramLabel(typeId);
  const tag = document.createElement("span");
  tag.className = "diagram-type-tag";
  tag.textContent = typeId;
  tag.title = `Mermaid · ${typeId}`;
  wrap.append(label, tag);
  return wrap;
}

export function buildMessageContent(text, { theme = "dark" } = {}) {
  initDiagrams(theme);
  initMarkdown();
  const root = document.createElement("div");
  root.className = "msg-rendered";

  for (const part of parseFencedBlocks(text)) {
    if (part.type === "text") {
      const el = document.createElement("div");
      el.className = "msg-text msg-markdown";
      el.innerHTML = renderMarkdown(part.content);
      root.appendChild(el);
      continue;
    }
    if (part.type === "mermaid") {
      const typeId = part.diagramType || detectMermaidDiagramType(part.content, part.lang);
      const typeLabel = getDiagramLabel(typeId);
      const box = document.createElement("div");
      box.className = "diagram-block";
      box.dataset.diagramType = typeId;
      const head = document.createElement("div");
      head.className = "diagram-head";
      head.appendChild(createDiagramLabel(typeId));
      const body = document.createElement("div");
      body.className = "diagram-body";
      if (part.complete && part.content.trim()) {
        body.setAttribute("data-mermaid", part.content.trim());
        body.setAttribute("data-diagram-type", typeId);
        body.classList.add("diagram-pending");
      } else {
        body.classList.add("diagram-streaming");
        const pre = document.createElement("pre");
        pre.className = "diagram-fallback";
        pre.textContent = part.content || "…";
        body.appendChild(pre);
        const hint = document.createElement("div");
        hint.className = "diagram-hint";
        hint.textContent = `${typeLabel}生成中…`;
        body.appendChild(hint);
      }
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "diagram-src-btn";
      toggle.textContent = "源码";
      toggle.addEventListener("click", () => {
        body.classList.toggle("show-source");
      });
      head.appendChild(toggle);
      const src = document.createElement("pre");
      src.className = "diagram-source";
      src.textContent = part.content;
      box.append(head, body, src);
      root.appendChild(box);
      continue;
    }
    if (part.type === "code") {
      const pre = document.createElement("pre");
      pre.className = "code-block";
      if (part.lang) {
        const tag = document.createElement("span");
        tag.className = "code-lang";
        tag.textContent = part.lang;
        pre.appendChild(tag);
      }
      const code = document.createElement("code");
      code.textContent = part.content + (part.complete ? "" : "\n…");
      pre.appendChild(code);
      root.appendChild(pre);
    }
  }
  return root;
}

/** mermaid 不可用时，把图表源码以纯文本展示，避免空白。 */
function showDiagramSourceFallback(el, code) {
  el.classList.remove("diagram-pending");
  el.classList.add("diagram-fallback-only");
  const pre = document.createElement("pre");
  pre.className = "diagram-fallback";
  pre.textContent = code;
  el.replaceChildren(pre);
}

async function renderOneMermaid(el, code) {
  const attempts = [code];
  const local = tryLocalMermaidFix(code);
  if (local !== code) attempts.push(local);

  let lastErr = null;
  for (const src of attempts) {
    const id = `auc-mmd-${++renderCounter}`;
    try {
      const { svg, bindFunctions } = await mermaid.render(id, src);
      el.innerHTML = svg;
      el.classList.remove("diagram-pending", "diagram-error", "diagram-repairing");
      el.classList.add("diagram-mermaid");
      el.dataset.mermaidCode = src;
      if (typeof bindFunctions === "function") bindFunctions(el);
      return { ok: true, code: src };
    } catch (err) {
      lastErr = err;
    }
  }
  return { ok: false, code, error: lastErr?.message || String(lastErr) };
}

function showDiagramError(el, code, error) {
  el.classList.add("diagram-error");
  el.dataset.mermaidCode = code;
  const pre = document.createElement("pre");
  pre.className = "diagram-fallback";
  pre.textContent = code;
  const msg = document.createElement("div");
  msg.className = "diagram-err";
  msg.textContent = `图表渲染失败: ${error}`;
  const hint = document.createElement("div");
  hint.className = "diagram-repair-hint";
  hint.textContent = "智能体正在尝试修复…";
  el.replaceChildren(pre, msg, hint);
}

export async function renderMermaidIn(container) {
  const pending = container.querySelectorAll("[data-mermaid]");
  const failures = [];
  for (const el of pending) {
    const code = (el.getAttribute("data-mermaid") || "").trim();
    el.removeAttribute("data-mermaid");
    if (!code) continue;
    if (!mermaid) {
      // CDN 不可达：降级显示源码，不计入「需修复」失败列表。
      showDiagramSourceFallback(el, code);
      continue;
    }
    const result = await renderOneMermaid(el, code);
    if (!result.ok) {
      showDiagramError(el, result.code, result.error);
      failures.push({ el, code: result.code, error: result.error });
    }
  }
  return failures;
}
