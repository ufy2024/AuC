"""智能体工作模式。"""

from auc.chat_agent import DEFAULT_CHAT_SYSTEM, build_chat_system_prompt
from auc.work_mode import (
    WORK_MODE_OVERVIEW,
    classify_work_mode,
    enrich_user_turn,
    list_work_modes,
    normalize_mode_choice,
    resolve_work_mode,
)


def test_system_prompt_includes_work_mode() -> None:
    prompt = build_chat_system_prompt("/tmp/ws")
    assert "工作模式" in prompt
    assert WORK_MODE_OVERVIEW.strip() in prompt
    assert "{sandbox}" not in prompt
    assert "/tmp/ws" in prompt


def test_default_chat_system_template_has_work_mode() -> None:
    assert "工作模式" in DEFAULT_CHAT_SYSTEM
    assert "实现" in DEFAULT_CHAT_SYSTEM


def test_list_work_modes() -> None:
    modes = list_work_modes()
    ids = {m["id"] for m in modes}
    assert "implement" in ids
    assert "debug" in ids
    assert "review" in ids


def test_classify_implement() -> None:
    assert classify_work_mode("帮我给游戏加个暂停按钮") == "implement"
    assert classify_work_mode("[Web 编辑器] 当前文件: a.py\n改一下") == "implement"


def test_classify_explain() -> None:
    assert classify_work_mode("什么是 ReAct 循环？") == "explain"


def test_classify_diagram() -> None:
    assert classify_work_mode("画一张机器学习学习路径流程图") == "diagram"


def test_classify_debug() -> None:
    assert classify_work_mode("backend 启动报错 500，帮我排查") == "debug"


def test_classify_review() -> None:
    assert classify_work_mode("帮我 review 一下这段代码") == "review"


def test_classify_explore() -> None:
    assert classify_work_mode("介绍一下这个项目的目录结构") == "explore"


def test_classify_clarify_short() -> None:
    assert classify_work_mode("好的") == "clarify"


def test_resolve_manual_override() -> None:
    mode, src = resolve_work_mode("什么是 Python？", selected="implement")
    assert mode == "implement"
    assert src == "manual"


def test_resolve_auto() -> None:
    mode, src = resolve_work_mode("什么是 Python？", selected="auto")
    assert mode == "explain"
    assert src == "auto"


def test_enrich_implement_turn() -> None:
    out, mode, src = enrich_user_turn("修改 backend 的 API")
    assert mode == "implement"
    assert src == "auto"
    assert "[工作模式：实现模式" in out
    assert "修改 backend" in out


def test_enrich_manual_diagram() -> None:
    out, mode, src = enrich_user_turn("随便聊聊", selected="diagram")
    assert mode == "diagram"
    assert src == "manual"
    assert "用户指定" in out


def test_normalize_mode_choice() -> None:
    assert normalize_mode_choice("AUTO") == "auto"
    assert normalize_mode_choice("debug") == "debug"
    assert normalize_mode_choice("invalid") == "auto"
