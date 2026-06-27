from __future__ import annotations

from auc.code_index import SymbolIndex
from auc.index_vector import VectorIndex, _cosine, available


def _fake_embed(texts):
    """玩具嵌入：按关键词映射到固定维度向量，便于断言相似度。"""
    out = []
    for t in texts:
        tl = t.lower()
        out.append(
            [
                1.0 if "auth" in tl or "login" in tl or "登录" in tl else 0.0,
                1.0 if "pay" in tl or "bill" in tl or "支付" in tl else 0.0,
                1.0 if "class" in tl else 0.0,
            ]
        )
    return out


def test_cosine():
    assert _cosine([1, 0], [1, 0]) == 1.0
    assert _cosine([1, 0], [0, 1]) == 0.0
    assert _cosine([], [1]) == 0.0
    assert _cosine([0, 0], [1, 1]) == 0.0


def test_available_with_injected_fn():
    assert available(_fake_embed) is True


def test_disabled_without_embedder(tmp_path):
    v = VectorIndex(str(tmp_path), embed_fn=None)
    # 注意：环境无 sentence-transformers 时 default_embedder()=None → 禁用
    if v.enabled:
        return  # 环境恰好装了，跳过该断言
    assert v.build(SymbolIndex(str(tmp_path))) == 0
    assert v.search("anything") == []


def test_build_and_search(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def login_user():\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "billing.py").write_text(
        "def charge_payment():\n    pass\n", encoding="utf-8"
    )
    idx = SymbolIndex(str(tmp_path))
    idx.refresh()
    v = VectorIndex(str(tmp_path), embed_fn=_fake_embed)
    assert v.enabled
    n = v.build(idx)
    assert n == 2
    # 持久化
    assert (tmp_path / ".auc" / "index" / "vectors.json").is_file()

    results = v.search("用户登录 auth", k=2)
    assert results
    assert results[0]["name"] == "login_user"

    results2 = v.search("支付 pay bill", k=2)
    assert results2[0]["name"] == "charge_payment"


def test_search_empty_index(tmp_path):
    v = VectorIndex(str(tmp_path), embed_fn=_fake_embed)
    assert v.search("") == []
    assert v.search("x") == []


def test_persistence_roundtrip(tmp_path):
    (tmp_path / "a.py").write_text("class Widget:\n    pass\n", encoding="utf-8")
    idx = SymbolIndex(str(tmp_path))
    idx.refresh()
    VectorIndex(str(tmp_path), embed_fn=_fake_embed).build(idx)
    # 新实例加载已存向量并可检索
    v2 = VectorIndex(str(tmp_path), embed_fn=_fake_embed)
    res = v2.search("class", k=1)
    assert res and res[0]["name"] == "Widget"
