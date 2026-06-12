/**
 * Material Icon Theme 风格文件树图标（基于 PKief / material-extensions，MIT）
 * 本地 SVG：/static/material-icons/
 */

const ICON_ROOT = "/static/material-icons";

/** 文件夹名（精确，小写）→ 图标 */
const FOLDER_BY_NAME = {
  events: "folder-event",
  event: "folder-event",
  integration: "folder-test",
  integrations: "folder-test",
  test: "folder-test",
  tests: "folder-test",
  __tests__: "folder-test",
  testing: "folder-test",
  tools: "folder-tools",
  tool: "folder-tools",
  web: "folder-public",
  www: "folder-public",
  public: "folder-public",
  static: "folder-public",
  dist: "folder-dist",
  build: "folder-dist",
  out: "folder-dist",
  docs: "folder-docs",
  doc: "folder-docs",
  documentation: "folder-docs",
  tmp: "folder-temp",
  temp: "folder-temp",
  roles: "folder-rules",
  rules: "folder-rules",
  examples: "folder-examples",
  example: "folder-examples",
  sample: "folder-examples",
  context: "folder-context",
  src: "folder-src",
  source: "folder-src",
  api: "folder-api",
  apis: "folder-api",
  assets: "folder-images",
  images: "folder-images",
  img: "folder-images",
  models: "folder-src",
  model: "folder-src",
  policy: "folder-rules",
  policies: "folder-rules",
  ports: "folder-api",
  loop: "folder-src",
  loops: "folder-src",
  node_modules: "folder-node",
  docker: "folder-docker",
  ".github": "folder-github",
  ".git": "folder-git",
  ".claude": "folder-robot",
  ".vscode": "folder-config",
  ".idea": "folder-config",
  ".ruff_cache": "folder-base",
  ".pytest_cache": "folder-python",
  ".mypy_cache": "folder-python",
  coverage: "folder-coverage",
  ci: "folder-ci",
  ".circleci": "folder-ci",
};

/** 文件夹名包含子串 → 图标（先匹配更长/更具体的规则） */
const FOLDER_BY_CONTAINS = [
  ["pytest", "folder-python"],
  ["github", "folder-github"],
  ["gitlab", "folder-git"],
  ["docker", "folder-docker"],
  ["node_modules", "folder-node"],
  ["claude", "folder-robot"],
  ["coverage", "folder-coverage"],
  ["mypy", "folder-python"],
  ["venv", "folder-config"],
  [".cache", "folder-config"],
  ["cache", "folder-temp"],
  ["plugin", "folder-plugin"],
  ["config", "folder-config"],
];

/** 扩展名 → 图标 */
const EXT_ICONS = {
  py: "python",
  pyi: "python",
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  ts: "typescript",
  tsx: "react_ts",
  jsx: "javascript",
  json: "json",
  jsonc: "json",
  md: "markdown",
  mdx: "markdown",
  html: "html",
  htm: "html",
  css: "css",
  scss: "css",
  sass: "css",
  less: "css",
  yaml: "yaml",
  yml: "yaml",
  rs: "rust",
  go: "go",
  java: "java",
  sh: "console",
  bash: "console",
  zsh: "console",
  fish: "console",
  toml: "toml",
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  ico: "image",
  svg: "svg",
  txt: "document",
  ini: "settings",
  cfg: "settings",
  conf: "settings",
  env: "settings",
  lock: "json",
  dockerfile: "docker",
};

/** 完整文件名（小写）→ 图标 */
const FILE_BY_NAME = {
  ".gitignore": "git",
  ".dockerignore": "git",
  ".gitattributes": "git",
  license: "key",
  "license.md": "key",
  "license.txt": "key",
  copying: "key",
  ".coverage": "istanbul",
  "coverage.json": "json",
  "py.typed": "python-misc",
  "pyproject.toml": "toml",
  "poetry.lock": "poetry",
  "dockerfile": "docker",
  "docker-compose.yml": "docker",
  "docker-compose.yaml": "docker",
  "vitest.config.ts": "vitest",
  "vitest.config.js": "vitest",
  "ruff.toml": "ruff",
};

const DEFAULT_FOLDER = "folder-base";
const DEFAULT_FILE = "document";

const AVAILABLE = new Set([
  "folder-base", "folder-event", "folder-test", "folder-tools", "folder-public",
  "folder-dist", "folder-docs", "folder-temp", "folder-rules", "folder-examples",
  "folder-context", "folder-src", "folder-api", "folder-images", "folder-github",
  "folder-python", "folder-robot", "folder-config", "folder-git", "folder-coverage",
  "folder-node", "folder-docker", "folder-ci", "folder-plugin",
  "python", "python-misc", "javascript", "typescript", "react_ts", "json", "git",
  "istanbul", "key", "document", "markdown", "readme", "yaml", "rust", "go", "java",
  "html", "css", "image", "svg", "toml", "console", "settings", "certificate",
  "ruff", "poetry", "vitest", "docker",
]);

function pickIcon(stem) {
  return AVAILABLE.has(stem) ? stem : DEFAULT_FILE;
}

function resolveFolderIcon(base) {
  if (FOLDER_BY_NAME[base]) return pickIcon(FOLDER_BY_NAME[base]);

  for (const [frag, icon] of FOLDER_BY_CONTAINS) {
    if (base.includes(frag)) return pickIcon(icon);
  }

  if (base.startsWith(".")) return pickIcon("folder-config");
  return DEFAULT_FOLDER;
}

export function materialIconUrl(stem) {
  return `${ICON_ROOT}/${stem}.svg`;
}

export function resolveMaterialIcon(entry) {
  const name = entry.name || "";
  const lower = name.toLowerCase();

  if (entry.type === "dir") {
    return resolveFolderIcon(lower);
  }

  if (FILE_BY_NAME[lower]) return pickIcon(FILE_BY_NAME[lower]);

  if (lower.startsWith("readme")) return pickIcon("readme");

  if (entry.is_image) return "image";
  if (entry.is_html) return "html";

  const dot = lower.lastIndexOf(".");
  if (dot > 0) {
    const ext = lower.slice(dot + 1);
    const base = lower.slice(0, dot);
    if (EXT_ICONS[ext]) return pickIcon(EXT_ICONS[ext]);
    if (base === "dockerfile" || base.endsWith(".dockerfile")) return pickIcon("docker");
    if (lower.startsWith(".") && ext) {
      if (ext === "coverage") return pickIcon("istanbul");
      if (ext === "env") return pickIcon("settings");
    }
  }

  return DEFAULT_FILE;
}

export function materialIconImg(stem, { size = 16, className = "" } = {}) {
  const cls = className ? ` class="mat-icon ${className}"` : ' class="mat-icon"';
  const src = materialIconUrl(stem);
  return `<img${cls} src="${src}" width="${size}" height="${size}" alt="" decoding="async" draggable="false"/>`;
}

export function materialTreeIconParts(entry, { size = 16 } = {}) {
  const stem = resolveMaterialIcon(entry);
  return {
    treeClass: `mat-${stem}`,
    html: materialIconImg(stem, { size, className: stem }),
  };
}
