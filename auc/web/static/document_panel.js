/** 办公文档预览：PDF / Word / Excel */

import { t } from "./i18n.js?v=2";

const $ = (sel) => document.querySelector(sel);

let mammothMod = null;
let xlsxMod = null;

async function loadMammoth() {
  if (!mammothMod) {
    mammothMod = await import("https://cdn.jsdelivr.net/npm/mammoth@1.8.0/+esm");
  }
  return mammothMod;
}

async function loadXlsx() {
  if (!xlsxMod) {
    xlsxMod = await import("https://cdn.jsdelivr.net/npm/xlsx@0.18.5/+esm");
  }
  return xlsxMod;
}

function docPanel() {
  return $("#doc-preview");
}

export function hideDocumentPreview() {
  const panel = docPanel();
  if (!panel) return;
  panel.classList.add("hidden");
  panel.replaceChildren();
}

function setLoading(panel, text) {
  panel.classList.remove("hidden");
  panel.innerHTML = `<p class="doc-preview-loading">${text}</p>`;
}

function setError(panel, message, rawUrl) {
  panel.innerHTML =
    `<div class="doc-preview-error">` +
    `<p>${message}</p>` +
    (rawUrl ? `<a class="doc-download-link" href="${rawUrl}" download>${t("doc.download")}</a>` : "") +
    `</div>`;
}

async function renderPdf(panel, data) {
  const src = data.preview_url || `/preview/${encodeURI(data.path)}`;
  panel.innerHTML =
    `<iframe class="doc-pdf-frame" title="${data.filename || data.path}" src="${src}"></iframe>`;
}

async function renderWord(panel, data) {
  const mammoth = await loadMammoth();
  const resp = await fetch(data.raw_url);
  if (!resp.ok) throw new Error(t("doc.loadFail", { status: resp.status }));
  const buf = await resp.arrayBuffer();
  const result = await mammoth.convertToHtml({ arrayBuffer: buf });
  const warnings = (result.messages || [])
    .filter((m) => m.type === "warning")
    .map((m) => m.message)
    .slice(0, 3);
  panel.innerHTML =
    `<div class="doc-word-body msg-rendered">${result.value}</div>` +
    (warnings.length
      ? `<p class="doc-preview-note">${t("doc.wordWarn", { warnings: warnings.join("；") })}</p>`
      : "");
}

async function renderExcel(panel, data) {
  const XLSX = await loadXlsx();
  const resp = await fetch(data.raw_url);
  if (!resp.ok) throw new Error(t("doc.loadFail", { status: resp.status }));
  const buf = await resp.arrayBuffer();
  const wb = XLSX.read(buf, { type: "array" });
  const parts = [];
  for (const name of wb.SheetNames) {
    const html = XLSX.utils.sheet_to_html(wb.Sheets[name], { id: `sheet-${name}` });
    parts.push(
      `<section class="doc-sheet">` +
      `<h3 class="doc-sheet-title">${name}</h3>` +
      `<div class="doc-sheet-table">${html}</div>` +
      `</section>`,
    );
  }
  panel.innerHTML = `<div class="doc-excel-body">${parts.join("")}</div>`;
}

function docTypeLabel(docType) {
  const keys = {
    ppt: "doc.kind.ppt",
    word_legacy: "doc.kind.wordLegacy",
  };
  return t(keys[docType] || "doc.kind.other");
}

function renderUnsupported(panel, data) {
  const label = docTypeLabel(data.doc_type);
  setError(panel, t("doc.unsupported", { kind: label }), data.raw_url);
}

export async function showDocumentPreview(data) {
  const panel = docPanel();
  if (!panel) return;
  setLoading(panel, t("doc.loading"));
  $("#monaco")?.style.setProperty("display", "none");

  if (!data.previewable) {
    renderUnsupported(panel, data);
    return;
  }

  try {
    if (data.doc_type === "pdf") {
      await renderPdf(panel, data);
    } else if (data.doc_type === "word") {
      await renderWord(panel, data);
    } else if (data.doc_type === "excel") {
      await renderExcel(panel, data);
    } else {
      renderUnsupported(panel, data);
    }
  } catch (err) {
    setError(panel, err.message || String(err), data.raw_url);
  }
}
