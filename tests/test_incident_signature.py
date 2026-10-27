"""告警指纹: 让"同一类故障"跨实例、跨时间聚到一起。

指纹用于 LLM Wiki 的同类经验召回(patterns/<sig>.md)。
它一旦带上 instance / 时间 / 具体数值, 就会退化成"每次都不同", 经验永远召不回;
反过来太粗又会把无关故障聚到一起。所以这里锁的是"取哪些字段"。
"""

from __future__ import annotations

import pytest

from app.incidents.signature import alert_view, compute_alert_signature

BASE_ALERT = {
    "alertname": "RedisDown",
    "service": "redis-master",
    "severity": "critical",
    "instance": "10.0.0.11:6379",
    "query": "",
    "summary": "redis 不可用",
}


def test_basic_signature_is_alertname_and_service() -> None:
    assert compute_alert_signature(BASE_ALERT) == "redisdown|redis-master"


def test_signature_is_case_and_whitespace_insensitive() -> None:
    noisy = {"alertname": "  Redis  DOWN ", "service": " Redis-Master "}
    assert compute_alert_signature(noisy) == "redis down|redis-master"


def test_signature_ignores_instance_and_severity() -> None:
    """换机器、换级别仍是同一类故障, 否则同类经验召不回来。"""
    other_instance = dict(BASE_ALERT, instance="10.0.0.99:6379", severity="warning")
    assert compute_alert_signature(other_instance) == compute_alert_signature(BASE_ALERT)


def test_signature_ignores_changing_numbers() -> None:
    a = dict(BASE_ALERT, summary="内存使用率 98%")
    b = dict(BASE_ALERT, summary="内存使用率 87%")
    assert compute_alert_signature(a) == compute_alert_signature(b)


def test_labels_fallback_for_raw_alertmanager_payload() -> None:
    payload = {"labels": {"alertname": "HighCPU", "service": "api-gateway"}}
    assert compute_alert_signature(payload) == "highcpu|api-gateway"


def test_manual_diagnosis_falls_back_to_first_eight_words() -> None:
    """手动诊断没有 alertname, 用 query 前 8 个词当近似指纹。"""
    payload = {"query": "我的 电脑 很卡 帮我 检查 cpu 内存 磁盘 和 高占用进程"}
    signature = compute_alert_signature(payload)

    assert signature == "我的 电脑 很卡 帮我 检查 cpu 内存 磁盘|"


def test_summary_is_used_when_query_missing() -> None:
    payload = {"summary": "接口 502 网关超时 请 排查 上游 服务"}
    signature = compute_alert_signature(payload)
    assert signature.startswith("接口 502 网关超时")


@pytest.mark.parametrize("payload", [None, {}, {"alertname": "", "service": "", "query": ""}, {"query": "   "}])
def test_no_usable_information_returns_empty(payload) -> None:
    """返回空串时调用方必须跳过同类召回, 不能拿空指纹去查。"""
    assert compute_alert_signature(payload) == ""


def test_unknown_keys_are_dropped_by_alert_view() -> None:
    """alert_view 是写入侧的 shaping, 多出来的字段不能漏进指纹。"""
    view = alert_view(dict(BASE_ALERT, extra="ignored", labels={"alertname": "x"}))

    assert set(view) == {"alertname", "service", "severity", "instance", "query", "summary"}
    assert view["alertname"] == "RedisDown"


def test_alert_view_only_reads_top_level_fields() -> None:
    """边界: shape 只认顶层字段。

    如果调用方拿到的是原始 Alertmanager payload(labels 嵌套), 直接过 alert_view
    会把 alertname/service 抹成空串 → 指纹为空 → 同类经验永远召不回。
    要么直接对原始 payload 算指纹, 要么先把 labels 展开成顶层。
    """
    raw = {"labels": {"alertname": "DiskFull", "service": "mysql-01"}}

    assert compute_alert_signature(alert_view(raw)) == ""
    assert compute_alert_signature(raw) == "diskfull|mysql-01"
