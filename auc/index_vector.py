"""R26 增量：可选向量语义层（extra `index`）。

在符号索引之上补「按语义找符号」：把每个符号的 `name@path`（+ kind/parent 上下文）嵌入为
向量，查询时按余弦相似度召回。**默认关闭以守零硬依赖**：

- 嵌入后端惰性导入 `sentence_transformers`；未安装 `available()` 返回 False，`build/search`
  no-op（调用方退回符号索引 + grep）。
- `embed_fn` 可注入（便于离线测试纯逻辑：构建 / 持久化 / 余弦召回），不依赖真实模型。

向量落 `.auc/index/vectors.json`（与符号索引同目录）。
"""

from __future__ import annotations

import importlib.util
import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Callable

EmbedFn = Callable[[list[str]], list[list[float]]]

DEFAULT_EMBED_MODEL = os.environ.get("AUC_EMBED_MODEL", "all-MiniLM-L6-v2")

# 默认嵌入器是「重对象」（加载模型权重 + 触网检查）。全进程构造一次并缓存，
# 避免 available() 与多个 VectorIndex 实例重复加载（曾导致启动时重复 "Loading weights"）。
_DEFAULT_EMBEDDER: EmbedFn | None = None
_DEFAULT_EMBEDDER_READY = False


def sentence_transformers_installed() -> bool:
    """仅检查 sentence-transformers 是否可导入——不构造模型、不触网、不打印 HF 警告。"""
    return importlib.util.find_spec("sentence_transformers") is not None


def default_embedder() -> EmbedFn | None:
    """惰性构造默认嵌入函数（sentence-transformers）；不可用返回 None。

    **仅在真正需要嵌入时调用**（首次 build/search），不要用于「能力探测」——
    那会把模型权重整个加载进来。构造一次后进程内缓存复用。
    """
    global _DEFAULT_EMBEDDER, _DEFAULT_EMBEDDER_READY
    if _DEFAULT_EMBEDDER_READY:
        return _DEFAULT_EMBEDDER

    _DEFAULT_EMBEDDER_READY = True
    try:
        # 降低 huggingface_hub 的 WARNING 噪声（如未设 HF_TOKEN 的未鉴权请求提示）。
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    try:
        model = SentenceTransformer(DEFAULT_EMBED_MODEL)
    except Exception:  # noqa: BLE001 模型下载/加载失败
        return None

    def _embed(texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in model.encode(texts)]

    _DEFAULT_EMBEDDER = _embed
    return _embed


def available(embed_fn: EmbedFn | None = None) -> bool:
    """是否具备语义层能力。

    **不加载模型**：注入了 embed_fn 即视为可用；否则仅检查 sentence-transformers
    是否可导入。模型权重推迟到首次 build/search 才加载（见 ``default_embedder``）。
    """
    if embed_fn is not None:
        return True
    return sentence_transformers_installed()


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
        # 显式注入的 embed_fn 立即生效；否则保持惰性，首次 build/search 才解析默认嵌入器，
        # 避免仅构造索引就加载模型权重。
        self._embed_fn = embed_fn
        self._embed_resolved = embed_fn is not None
        self.items: list[dict[str, Any]] = []
        self.vectors: list[list[float]] = []
        self._loaded = False

    def _embedder(self) -> EmbedFn | None:
        """解析嵌入器（惰性，仅一次）；不可用返回 None。"""
        if not self._embed_resolved:
            self._embed_fn = default_embedder()
            self._embed_resolved = True
        return self._embed_fn

    @property
    def enabled(self) -> bool:
        """是否具备语义能力——不触发模型加载。

        已注入/已解析出 embed_fn 则按其是否存在判断；否则按 sentence-transformers
        是否可导入判断（真正的模型加载推迟到 build/search）。
        """
        if self._embed_resolved:
            return self._embed_fn is not None
        return available()

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
        from auc.fslock import atomic_write_text, file_lock

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # 原子写 + 跨进程锁：避免并发 build/save 读到半截或互相覆盖损坏。
            with file_lock(self._path.with_suffix(".json.lock")):
                atomic_write_text(
                    self._path,
                    json.dumps(
                        {"items": self.items, "vectors": self.vectors},
                        ensure_ascii=False,
                    ),
                )
        except OSError:
            pass

    def build(self, symbol_index: Any) -> int:
        """从 SymbolIndex 重建向量库；未启用返回 0。返回嵌入的符号数。"""
        embed = self._embedder()
        if embed is None:
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
        self.vectors = embed(texts)
        self.items = items
        self.save()
        return len(items)

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """语义召回 top-k；未启用或空库返回 []。"""
        if not (query or "").strip():
            return []
        embed = self._embedder()
        if embed is None:
            return []
        self.load()
        if not self.vectors:
            return []
        qvec = embed([query])[0]
        scored = [
            {**item, "score": _cosine(qvec, vec)}
            for item, vec in zip(self.items, self.vectors)
        ]
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[: max(1, k)]
