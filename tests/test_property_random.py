"""轻量属性测试（固定种子随机化，零新依赖）：JSON 解析与路径规范化。"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path

import pytest

from auc.model.json_util import safe_parse_tool_input
from auc.sandbox import SandboxViolationError, resolve_under_sandbox

_RNG = random.Random(20260611)


def _rand_key() -> str:
    return "".join(_RNG.choices(string.ascii_lowercase, k=_RNG.randint(1, 8)))


def _rand_value(depth: int = 0):  # noqa: ANN202
    kind = _RNG.randint(0, 5 if depth < 2 else 3)
    if kind == 0:
        return _RNG.randint(-(10**6), 10**6)
    if kind == 1:
        return _RNG.random() * 1000
    if kind == 2:
        chars = string.ascii_letters + string.digits + " 中文混排\"\\'{}[]:,"
        return "".join(_RNG.choices(chars, k=_RNG.randint(0, 20)))
    if kind == 3:
        return _RNG.choice([True, False, None])
    if kind == 4:
        return [_rand_value(depth + 1) for _ in range(_RNG.randint(0, 4))]
    return {_rand_key(): _rand_value(depth + 1) for _ in range(_RNG.randint(0, 4))}


def _rand_obj() -> dict:
    return {_rand_key(): _rand_value() for _ in range(_RNG.randint(0, 6))}


def test_safe_parse_roundtrip_random_objects() -> None:
    """性质：任意合法 JSON 对象（含空对象）序列化后解析必须无损还原。"""
    for _ in range(200):
        obj = _rand_obj()
        raw = json.dumps(obj, ensure_ascii=False)
        assert safe_parse_tool_input(raw) == obj


def test_safe_parse_empty_object_returns_empty_dict() -> None:
    """无参工具调用常见输入：空对象/空串必须直接返回 {}，不得抛错。"""
    assert safe_parse_tool_input("{}") == {}
    assert safe_parse_tool_input("  {} ") == {}
    assert safe_parse_tool_input("") == {}
    assert safe_parse_tool_input("   ") == {}


def test_safe_parse_truncated_returns_dict_or_value_error() -> None:
    """性质：任意位置截断的 JSON 要么修复为 dict，要么抛 ValueError，绝不抛其他异常。"""
    for _ in range(60):
        obj = _rand_obj()
        raw = json.dumps(obj, ensure_ascii=False)
        for cut in sorted(_RNG.sample(range(len(raw) + 1), k=min(10, len(raw) + 1))):
            try:
                out = safe_parse_tool_input(raw[:cut], tool_name="t")
            except ValueError:
                continue
            assert isinstance(out, dict)


def test_safe_parse_garbage_returns_dict_or_value_error() -> None:
    """性质：随机噪声输入要么返回 dict，要么抛 ValueError（受控失败）。"""
    chars = string.printable + "中文鍵値🎉"
    for _ in range(100):
        noise = "".join(_RNG.choices(chars, k=_RNG.randint(0, 40)))
        try:
            out = safe_parse_tool_input(noise, tool_name="t")
        except ValueError:
            continue
        assert isinstance(out, dict)


def _rand_safe_relpath() -> str:
    segs = []
    for _ in range(_RNG.randint(1, 4)):
        segs.append(
            "".join(_RNG.choices(string.ascii_lowercase + string.digits + "_-", k=_RNG.randint(1, 8)))
        )
    return "/".join(segs)


def test_resolve_under_sandbox_safe_paths_stay_inside(tmp_path: Path) -> None:
    """性质：不含 .. 的相对路径解析结果必在沙盒根内。"""
    root = tmp_path.resolve()
    for _ in range(100):
        rel = _rand_safe_relpath()
        resolved = resolve_under_sandbox(str(root), rel)
        assert resolved.is_relative_to(root)


def test_resolve_under_sandbox_escape_always_blocked(tmp_path: Path) -> None:
    """性质：任意构造的 .. 逃逸路径要么被拒绝，要么解析后仍在根内。"""
    root = tmp_path / "inner"
    root.mkdir()
    for _ in range(100):
        ups = "../" * _RNG.randint(1, 6)
        rel = ups + _rand_safe_relpath()
        try:
            resolved = resolve_under_sandbox(str(root), rel)
        except SandboxViolationError:
            continue
        assert resolved.is_relative_to(root.resolve())


def test_resolve_under_sandbox_absolute_outside_blocked(tmp_path: Path) -> None:
    for candidate in ("/etc/passwd", "/tmp/x", str(tmp_path.parent / "other")):
        with pytest.raises(SandboxViolationError):
            resolve_under_sandbox(str(tmp_path / "inner2"), candidate)
