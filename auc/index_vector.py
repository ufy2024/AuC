"""R26 增量：可选向量语义层（extra `index`）。

在符号索引之上补「按语义找符号」：把每个符号的 `name@path`（+ kind/parent 上下文）嵌入为
向量，查询时按余弦相似度召回。**默认关闭以守零硬依赖**：

- 嵌入后端惰性导入 `sentence_transformers`；未安装 `available()` 返回 False，`build/search`
  no-op（调用方退回符号索引 + grep）。
- `embed_fn` 可注入（便于离线测试纯逻辑：构建 / 持久化 / 余弦召回），不依赖真实模型。

向量落 `.auc/index/vectors.json`（与符号索引同目录）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

EmbedFn = Callable[[list[str]], list[list[float]]]


def default_embedder() -> EmbedFn | None:
    """惰性构造默认嵌入函数（sentence-transformers）；不可用返回 None。"""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    try:
        model = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:  # noqa: BLE001 模型下载/加载失败
        return None

    def _embed(texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in model.encode(texts)]

    return _embed


def available(embed_fn: EmbedFn | None = None) -> bool:
    return (embed_fn or default_embedder()) is not None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _symbol_text(sym: Any, path: str) -> str:
    parent = f" in {sym.parent}" if getattr(sym, "parent", "") else ""
    return f"{sym.kind} {sym.name}{parent} ({path})"


class VectorIndex:
    """符号语义向量层；落 `.auc/index/vectors.json`。embed_fn 缺省即降级 no-op。"""

    def __init__(self, sandbox_root: str, *, embed_fn: EmbedFn | None = None) -> None:
        self.root = Path(sandbox_root).resolve()
        self._path = self.root / ".auc" / "index" / "vectors.json"
        self._embed = embed_fn if embed_fn is not None else default_embedder()
        self.items: list[dict[str, Any]] = []
        self.vectors: list[list[float]] = []
        self._loaded = False

    @property
    def enabled(self) -> bool:
        return self._embed is not None

    def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._path.is_file():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self.items = list(data.get("items") or [])
        self.vectors = [list(map(float, v)) for v in (data.get("vectors") or [])]

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {"items": self.items, "vectors": self.vectors},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def build(self, symbol_index: Any) -> int:
        """从 SymbolIndex 重建向量库；未启用返回 0。返回嵌入的符号数。"""
        if not self.enabled:
            return 0
        symbol_index.load()
        items: list[dict[str, Any]] = []
        texts: list[str] = []
        for entry in symbol_index.files.values():
            for sym in entry.symbols:
                items.append(
                    {
                        "name": sym.name,
                        "kind": sym.kind,
                        "parent": getattr(sym, "parent", ""),
                        "path": entry.path,
                        "line": sym.line,
                    }
                )
                texts.append(_symbol_text(sym, entry.path))
        if not texts:
            self.items, self.vectors = [], []
            self.save()
            return 0
        self.vectors = self._embed(texts)  # type: ignore[misc]
        self.items = items
        self.save()
        return len(items)

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """语义召回 top-k；未启用或空库返回 []。"""
        if not self.enabled or not (query or "").strip():
            return []
        self.load()
        if not self.vectors:
            return []
        qvec = self._embed([query])[0]  # type: ignore[misc]
        scored = [
            {**item, "score": _cosine(qvec, vec)}
            for item, vec in zip(self.items, self.vectors)
        ]
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[: max(1, k)]
