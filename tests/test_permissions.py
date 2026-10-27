"""三态权限决策矩阵 (allow / ask / deny)。

为什么值得单独测: 这是"Agent 会不会乱动生产"的唯一闸门。
需求文档里写的是四层防御, 但真正生效的是这里的短路顺序:
    Layer0 Skill 硬墙 → BYPASS 直通 → Layer1 Mode → Layer2 Guardrail → allow
顺序错一格, 就会出现"没在白名单里但被 BYPASS 放行"这类越权。

本文件用真实 TOOL_META 里的工具名断言, 不 mock 元数据, 这样元数据改错也能被抓到。
"""

from __future__ import annotations

import pytest

import app.runtime.tool_filter as tool_filter
from app.runtime.permissions import (
    PermissionDecision,
    PermissionMode,
    evaluate_permission,
    parse_permission_mode,
)
from app.runtime.tool_filter import NOTIFICATION_TOOLS
from tests._helpers import patched

# (tool, skill_allowed, mode, block_high_risk, allow_notification) -> (behavior, reason_type)
MATRIX = [
    # --- Layer0: Skill 白名单是硬墙 ---
    ("docker_restart", set(), PermissionMode.NORMAL, True, False, "deny", "skill_allowlist"),
    ("docker_restart", set(), PermissionMode.BYPASS, True, False, "deny", "skill_allowlist"),
    ("never_registered_tool", set(), PermissionMode.NORMAL, True, False, "deny", "skill_allowlist"),
    # --- 只读豁免: 白名单外的只读查询工具仍可用(避免诊断拿不到数据) ---
    ("list_top_processes", set(), PermissionMode.NORMAL, True, False, "allow", "ok"),
    ("web_search", set(), PermissionMode.NORMAL, True, False, "allow", "ok"),
    ("search_knowledge_base", {"search_knowledge_base"}, PermissionMode.READ_ONLY, True, False, "allow", "ok"),
    # --- BYPASS 直通(仅在已过白名单之后) ---
    ("docker_restart", {"docker_restart"}, PermissionMode.BYPASS, True, False, "allow", "mode_bypass"),
    # --- Layer1: Mode ---
    ("docker_restart", {"docker_restart"}, PermissionMode.READ_ONLY, True, False, "deny", "mode_read_only"),
    ("docker_restart", {"docker_restart"}, PermissionMode.ASK_DESTRUCTIVE, True, False, "ask", "mode_ask"),
    # 未登记工具 fail-closed: 只读模式下视为有副作用
    ("never_registered_tool", {"never_registered_tool"}, PermissionMode.READ_ONLY, True, False, "deny", "mode_read_only"),
    # --- Layer2: 静态 Guardrail ---
    ("docker_restart", {"docker_restart"}, PermissionMode.NORMAL, True, False, "deny", "guardrail_high"),
    ("docker_restart", {"docker_restart"}, PermissionMode.NORMAL, False, False, "allow", "ok"),
    # ask 优先于 guardrail: 先给人工审批机会, 而不是直接拒绝
    ("docker_restart", {"docker_restart"}, PermissionMode.ASK_DESTRUCTIVE, False, False, "ask", "mode_ask"),
]


@pytest.mark.parametrize(
    "tool,allowed,mode,block_high_risk,allow_notification,behavior,reason_type",
    MATRIX,
)
def test_permission_matrix(
    tool: str,
    allowed: set[str],
    mode: PermissionMode,
    block_high_risk: bool,
    allow_notification: bool,
    behavior: str,
    reason_type: str,
) -> None:
    decision = evaluate_permission(
        tool,
        None,
        skill_allowed=allowed,
        mode=mode,
        block_high_risk=block_high_risk,
        allow_notification=allow_notification,
    )

    assert decision.behavior == behavior
    assert decision.reason_type == reason_type, decision.reason


def test_notification_tools_are_blocked_until_authorized() -> None:
    """通知类工具单独开关控制: 默认关, 打开后放行。"""
    fake_notify = "notify_test_tool"
    with patched(
        tool_filter,
        NOTIFICATION_TOOLS=NOTIFICATION_TOOLS | {fake_notify},
    ):
        blocked = evaluate_permission(
            fake_notify,
            None,
            skill_allowed={fake_notify},
            mode=PermissionMode.NORMAL,
            block_high_risk=True,
            allow_notification=False,
        )
        allowed = evaluate_permission(
            fake_notify,
            None,
            skill_allowed={fake_notify},
            mode=PermissionMode.NORMAL,
            block_high_risk=True,
            allow_notification=True,
        )

    assert blocked.behavior == "deny"
    assert blocked.reason_type == "guardrail_notify"
    assert allowed.behavior == "allow"


def test_deny_reason_is_human_readable() -> None:
    """每个 deny/ask 都要能被审计直接读懂, 不能是空字符串。"""
    decision = evaluate_permission(
        "docker_restart",
        None,
        skill_allowed=set(),
        mode=PermissionMode.NORMAL,
    )
    assert decision.reason, "deny 必须带可读原因"
    assert "docker_restart" in decision.reason


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("read_only", PermissionMode.READ_ONLY),
        ("READ_ONLY", PermissionMode.READ_ONLY),
        ("  Normal  ", PermissionMode.NORMAL),
        ("ask_destructive", PermissionMode.ASK_DESTRUCTIVE),
        ("bypass", PermissionMode.BYPASS),
        # 容错: 未知/空值降级 NORMAL, 绝不因拼错而落到 BYPASS
        ("read-onli", PermissionMode.NORMAL),
        ("", PermissionMode.NORMAL),
        (None, PermissionMode.NORMAL),
    ],
)
def test_parse_permission_mode(raw, expected: PermissionMode) -> None:
    assert parse_permission_mode(raw) is expected


def test_ask_counts_as_blocked_until_approved() -> None:
    ask = PermissionDecision(behavior="ask", reason_type="mode_ask")
    allow = PermissionDecision(behavior="allow", reason_type="ok")
    deny = PermissionDecision(behavior="deny", reason_type="guardrail_high")

    assert ask.is_blocked() is True
    assert ask.is_allowed() is False
    assert allow.is_allowed() is True
    assert allow.is_blocked() is False
    assert deny.is_blocked() is True
