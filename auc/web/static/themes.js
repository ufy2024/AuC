/** 颜色主题与图标主题注册（类似 VS Code 主题选择） */

export const COLOR_THEMES = [
  {
    id: "monokai",
    label: "Monokai",
    description: "默认 · 经典 Monokai 配色",
    dark: true,
    monaco: "vs-dark",
    preview: ["#272822", "#f8f8f2", "#a6e22e", "#f92672", "#fd971f", "#66d9ef", "#ae81ff"],
  },
  {
    id: "dark-plus",
    label: "Dark+",
    description: "JupyterLab 风格深色",
    dark: true,
    monaco: "vs-dark",
    preview: ["#1a1d21", "#e6edf3", "#3793ef", "#f37726", "#c678dd", "#2d333b", "#8b949e"],
  },
  {
    id: "one-dark",
    label: "One Dark",
    description: "Atom One Dark",
    dark: true,
    monaco: "vs-dark",
    preview: ["#282c34", "#abb2bf", "#61afef", "#c678dd", "#98c379", "#e5c07b", "#d19a66"],
  },
  {
    id: "github-dark",
    label: "GitHub Dark",
    description: "GitHub 深色",
    dark: true,
    monaco: "vs-dark",
    preview: ["#0d1117", "#e6edf3", "#58a6ff", "#f0883e", "#d2a8ff", "#21262d", "#8b949e"],
  },
  {
    id: "solarized-dark",
    label: "Solarized Dark",
    description: "Solarized 深色",
    dark: true,
    monaco: "vs-dark",
    preview: ["#002b36", "#93a1a1", "#268bd2", "#2aa198", "#b58900", "#cb4b16", "#6c71c4"],
  },
  {
    id: "light-plus",
    label: "Light+",
    description: "默认浅色 · 清新简约",
    dark: false,
    monaco: "vs",
    preview: ["#ffffff", "#1a2332", "#3b82f6", "#6366f1", "#f37726", "#f1f5f9", "#64748b"],
  },
  {
    id: "github-light",
    label: "GitHub Light",
    description: "GitHub 浅色",
    dark: false,
    monaco: "vs",
    preview: ["#ffffff", "#1f2328", "#0969da", "#bc4c00", "#8250df", "#f6f8fa", "#656d76"],
  },
  {
    id: "high-contrast",
    label: "High Contrast",
    description: "高对比度（无障碍）",
    dark: true,
    monaco: "hc-black",
    preview: ["#000000", "#ffffff", "#1aebff", "#ffff00", "#ff0000", "#1a1a1a", "#6fc3df"],
  },
];

export const ICON_THEMES = [
  {
    id: "office-material",
    label: "Office Material",
    description: "默认 · Material 彩色文件图标",
    preview: [
      "material:folder-github",
      "material:folder-test",
      "material:folder-temp",
      "material:python",
      "material:json",
      "material:key",
      "material:istanbul",
    ],
  },
  {
    id: "default",
    label: "Default",
    description: "Lucide 线框图标",
    preview: ["folder", "file", "fileCode"],
  },
  {
    id: "minimal",
    label: "Minimal",
    description: "极简细线",
    preview: ["folder", "file", "fileCode"],
  },
  {
    id: "seti",
    label: "Seti",
    description: "类 Seti · 文件类型着色",
    preview: ["folder", "file", "fileCode"],
  },
];

const COLOR_MAP = Object.fromEntries(COLOR_THEMES.map((t) => [t.id, t]));
const ICON_MAP = Object.fromEntries(ICON_THEMES.map((t) => [t.id, t]));

export function getColorTheme(id) {
  return COLOR_MAP[id] || COLOR_MAP.monokai;
}

export function getIconThemeMeta(id) {
  return ICON_MAP[id] || ICON_MAP["office-material"];
}

export function isColorThemeDark(id) {
  return getColorTheme(id).dark;
}

export function monacoThemeFor(colorThemeId) {
  return getColorTheme(colorThemeId).monaco;
}

export function loadStoredColorTheme() {
  let id = localStorage.getItem("auc-color-theme");
  if (id === "molokai") id = "monokai";
  return id && COLOR_MAP[id] ? id : "monokai";
}

export function loadStoredIconTheme() {
  const id = localStorage.getItem("auc-icon-theme");
  return id && ICON_MAP[id] ? id : "office-material";
}

export function applyColorTheme(id) {
  const theme = getColorTheme(id);
  const app = document.getElementById("app");
  if (app) app.dataset.colorTheme = theme.id;
  localStorage.setItem("auc-color-theme", theme.id);
  return theme.id;
}

export function applyIconTheme(id) {
  const theme = getIconThemeMeta(id);
  const app = document.getElementById("app");
  if (app) app.dataset.iconTheme = theme.id;
  localStorage.setItem("auc-icon-theme", theme.id);
  return theme.id;
}
