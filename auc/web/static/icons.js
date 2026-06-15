/** 内联 SVG 图标 · 支持多图标主题（类似 VS Code Icon Theme） */

import { materialTreeIconParts, materialIconImg } from "./material_file_icons.js";

let activeIconTheme = "office-material";

const STROKE = {
  default: "1.75",
  minimal: "1.35",
  seti: "1.65",
  "office-material": "1.5",
};

const COLORED_ICON_THEMES = new Set(["seti"]);

const ICONS = {
  folder: `<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/>`,
  folderFilled: `<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" fill="currentColor" stroke="none"/>`,
  file: `<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>`,
  fileMinimal: `<path d="M6 4h8l4 4v12H6z"/><path d="M14 4v4h4"/>`,
  fileImage: `<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><circle cx="10" cy="13" r="2"/><path d="m20 17-3.5-3.5a1 1 0 0 0-1.4 0L9 20"/>`,
  fileCode: `<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="m10 13-2 2 2 2"/><path d="m14 13 2 2-2 2"/>`,
  rocket: `<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>`,
  message: `<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>`,
  refresh: `<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>`,
  plus: `<path d="M12 5v14"/><path d="M5 12h14"/>`,
  filePlus: `<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M12 18v-6"/><path d="M9 15h6"/>`,
  folderPlus: `<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/><path d="M12 11v6"/><path d="M9 14h6"/>`,
  chevronDown: `<path d="m6 9 6 6 6-6"/>`,
  chevronUp: `<path d="m6 15 6-6 6 6"/>`,
  chevronLeft: `<path d="m15 18-6-6 6-6"/>`,
  chevronRight: `<path d="m9 18 6-6-6-6"/>`,
  panelLeftClose: `<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18"/><path d="m16 15-3-3 3-3"/>`,
  trash: `<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>`,
  image: `<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>`,
  arrowUp: `<path d="m12 19V5"/><path d="m5 12 7-7 7 7"/>`,
  dir: `<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>`,
  palette: `<circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>`,
  check: `<path d="M20 6 9 17l-5-5"/>`,
  terminal: `<path d="M12 19h8"/><path d="m4 17 6-6-6-6"/><rect width="20" height="14" x="2" y="5" rx="2"/>`,
  pencil: `<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>`,
  eye: `<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>`,
  eyeOff: `<path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/><line x1="2" x2="22" y1="2" y2="22"/>`,
};

export function setActiveIconTheme(id) {
  activeIconTheme = id || "office-material";
}

export function getActiveIconTheme() {
  return activeIconTheme;
}

export function icon(name, { size = 16, className = "", theme } = {}) {
  const paths = ICONS[name];
  if (!paths) return "";
  const th = theme || activeIconTheme;
  const strokeW = STROKE[th] || STROKE.default;
  const filled = name === "folderFilled" || (th === "office-material" && name === "dir");
  const cls = className ? ` class="ui-icon ${className}"` : ' class="ui-icon"';
  const strokeAttrs = filled
    ? ' fill="currentColor" stroke="none"'
    : ` fill="none" stroke="currentColor" stroke-width="${strokeW}" stroke-linecap="round" stroke-linejoin="round"`;
  return `<svg${cls} width="${size}" height="${size}" viewBox="0 0 24 24"${strokeAttrs} aria-hidden="true">${paths}</svg>`;
}

export function setButtonIcon(btn, name, { size = 16 } = {}) {
  if (!btn) return;
  btn.innerHTML = icon(name, { size });
}

/** 文件树条目图标名 + CSS 修饰类 */
export function treeEntryIconSpec(entry) {
  if (entry.type === "dir") {
    const filled = activeIconTheme === "seti" || activeIconTheme === "office-material";
    return {
      name: filled ? "folderFilled" : "dir",
      extraClass: "dir",
      extClass: "dir",
    };
  }
  if (entry.is_image) {
    return { name: "fileImage", extraClass: "img ext-img", extClass: "ext-img" };
  }
  if (entry.is_html) {
    return { name: "fileCode", extraClass: "html ext-html", extClass: "ext-html" };
  }
  const ext = (entry.name || "").split(".").pop()?.toLowerCase() || "";
  const fileName = activeIconTheme === "minimal" ? "fileMinimal" : "file";
  return {
    name: fileName,
    extraClass: `file ext-${ext}`,
    extClass: ext ? `ext-${ext}` : "file",
  };
}

export function treeEntryIconParts(entry, { size = 16 } = {}) {
  if (activeIconTheme === "office-material") {
    return materialTreeIconParts(entry, { size });
  }
  const spec = treeEntryIconSpec(entry);
  const treeClass = COLORED_ICON_THEMES.has(activeIconTheme) ? spec.extClass : "";
  const iconClass = spec.extraClass.split(/\s+/)[0] || "";
  return {
    treeClass,
    html: icon(spec.name, { size, className: iconClass }),
  };
}

export function treeEntryIconHtml(entry, opts = {}) {
  return treeEntryIconParts(entry, opts).html;
}
