from __future__ import annotations

from pathlib import Path

from auc.web.documents import (
    document_type,
    is_previewable_document,
    read_document_file,
)


def test_document_type_mapping() -> None:
    assert document_type("a.pdf") == "pdf"
    assert document_type("b.docx") == "word"
    assert document_type("c.doc") == "word_legacy"
    assert document_type("d.xlsx") == "excel"
    assert document_type("e.pptx") == "ppt"
    assert document_type("f.py") is None


def test_is_previewable_document() -> None:
    assert is_previewable_document("r.pdf")
    assert is_previewable_document("r.docx")
    assert not is_previewable_document("r.doc")
    assert not is_previewable_document("r.pptx")


def test_read_document_file_pdf(tmp_path: Path) -> None:
    f = tmp_path / "docs" / "paper.pdf"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"%PDF-1.4")
    data = read_document_file(str(tmp_path), "docs/paper.pdf")
    assert data["kind"] == "document"
    assert data["doc_type"] == "pdf"
    assert data["previewable"] is True
    assert data["preview_url"] == "/preview/docs/paper.pdf"
    assert "raw_url" in data


def test_read_document_file_ppt_not_previewable(tmp_path: Path) -> None:
    f = tmp_path / "slide.pptx"
    f.write_bytes(b"pk")
    data = read_document_file(str(tmp_path), "slide.pptx")
    assert data["doc_type"] == "ppt"
    assert data["previewable"] is False
