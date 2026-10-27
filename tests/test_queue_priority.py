"""告警 → 队列优先级的映射。

Redis Streams 按 level 分 stream 消费, critical 必须先于 low 被 Worker 领走。
映射错一格, 就是"P0 告警排在批量巡检后面"。这两个函数是纯函数, 不需要 Redis。
"""

from __future__ import annotations

import pytest

from app.queue.redis_streams import PRIORITY_LEVELS, level_for_priority, level_for_severity


def test_priority_levels_are_ordered_most_urgent_first() -> None:
    """列表顺序就是消费顺序, 不能随便调换。"""
    assert PRIORITY_LEVELS[0] == "critical"
    assert PRIORITY_LEVELS[-1] == "low"


@pytest.mark.parametrize(
    "severity,expected",
    [
        ("critical", "critical"),
        ("CRITICAL", "critical"),
        ("page", "critical"),
        ("p0", "critical"),
        ("high", "high"),
        ("P1", "high"),
        ("warning", "normal"),
        ("p2", "normal"),
        ("info", "low"),
        ("low", "low"),
        ("p3", "low"),
        ("unknown-severity", "normal"),
        ("", "normal"),
        (None, "normal"),
    ],
)
def test_level_for_severity(severity, expected: str) -> None:
    assert level_for_severity(severity) == expected


def test_manual_diagnosis_defaults_to_normal() -> None:
    """手动诊断没有 severity, 默认 normal, 不抢占告警通道。"""
    assert level_for_severity("") == "normal"


@pytest.mark.parametrize(
    "priority,expected",
    [
        (0, "critical"),
        (10, "critical"),
        (11, "high"),
        (50, "high"),
        (51, "normal"),
        (100, "normal"),
        (101, "low"),
        (999, "low"),
    ],
)
def test_level_for_priority(priority: int, expected: str) -> None:
    assert level_for_priority(priority) == expected


@pytest.mark.parametrize("bad", ["abc", "", None, {"x": 1}])
def test_level_for_priority_is_total_function(bad) -> None:
    """脏数据不能让入队失败, 统一降级 normal。"""
    assert level_for_priority(bad) == "normal"
