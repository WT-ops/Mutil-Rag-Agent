"""诊断目标环境识别与工具隔离。

注意：Docker API 内的本机指标不等于 Windows 宿主机指标。
当请求仅把另一个环境作为对照时，优先识别明确要求采集的诊断目标。
"""

import re
from typing import Literal, Sequence

from langchain_core.tools import BaseTool

TargetEnv = Literal[
    "windows_host",
    "docker_container",
    "unspecified",
]

# 这些工具在 Docker API 容器中采集的是容器环境
LOCAL_SYSTEM_TOOLS = {
    "get_local_system_overview",
    "get_local_cpu_memory",
    "get_local_disk_usage",
    "list_top_processes",
}

WINDOWS_TOOLS = {
    "get_windows_host_metrics",
}

DOCKER_TOOLS = {
    "docker_ps",
    "docker_stats",
    "docker_logs",
    "docker_inspect",
}

# 当前部署中的 winlog MCP 位于 Linux 容器内
UNVERIFIED_TOOLS = {
    "query_windows_event",
}

# 防止二级 Agent 绕过主 Executor 的环境过滤
BYPASS_TOOLS = {
    "delegate_to_evidence_collector",
}

_WINDOWS_EXPLICIT = ("windows", "win11", "win10")
_WINDOWS_GENERIC = ("我的电脑", "我电脑", "我的笔记本", "这台电脑")
_DOCKER_HINTS = ("docker", "container", "容器", "kubernetes", "k8s")
_ACTION_RE = re.compile(
    r"诊断|检查|检测|排查|分析|查看|获取|采集|监测|监控|统计|读取|查询|定位|评估|"
    r"diagnose|inspect|check|monitor|analy[sz]e|collect|investigate"
)
_NEGATED_ACTION_RE = re.compile(
    r"(?:不要|不应|不得|不能|无需|不必|禁止|切勿|别|避免)\s*"
    r"(?:诊断|检查|检测|排查|分析|查看|获取|采集|监测|监控|统计|读取|查询|定位|评估|"
    r"diagnose|inspect|check|monitor|analy[sz]e|collect|investigate)"
)
# 这些标记后的环境一般是排除项或对照说明，不是该动作的采集目标。
_CONTRAST_RE = re.compile(r"而不是|而非|不要|不得|不应|不能|区分|区别|避免|作为对照|用作对照")
_CLAUSE_RE = re.compile(r"[，,。；;！!？?\n]+")


def _classify_mention(text: str) -> TargetEnv:
    explicit_windows = any(hint in text for hint in _WINDOWS_EXPLICIT)
    generic_windows = any(hint in text for hint in _WINDOWS_GENERIC)
    docker = any(hint in text for hint in _DOCKER_HINTS)

    if docker and explicit_windows:
        return "unspecified"
    # “我电脑上的 Docker 容器”以明确的容器为诊断对象。
    if docker:
        return "docker_container"
    if explicit_windows or generic_windows:
        return "windows_host"
    return "unspecified"


def detect_target_environment(query: str) -> TargetEnv:
    """结合诊断动作和对象识别目标，而不是仅统计两类关键词。"""
    text = (query or "").casefold()
    action_targets: set[TargetEnv] = set()

    for clause in _CLAUSE_RE.split(text):
        # “不要采集 Windows 数据”不应被当作目标采集指令。
        clause = _NEGATED_ACTION_RE.sub("", clause)
        action = _ACTION_RE.search(clause)
        if action is None:
            continue

        object_text = clause[action.end():]
        object_text = _CONTRAST_RE.split(object_text, maxsplit=1)[0]
        target = _classify_mention(object_text)
        if target != "unspecified":
            action_targets.add(target)
        elif any(h in object_text for h in (*_WINDOWS_EXPLICIT, *_DOCKER_HINTS)):
            # 同一动作明确要求两类环境，不可默认只诊断其中一种。
            if (
                any(h in object_text for h in _WINDOWS_EXPLICIT)
                and any(h in object_text for h in _DOCKER_HINTS)
            ):
                return "unspecified"

    if len(action_targets) == 1:
        return next(iter(action_targets))
    if len(action_targets) > 1:
        return "unspecified"

    # 无明确诊断动作时维持保守规则：同时出现两类环境就不猜目标。
    return _classify_mention(text)


def filter_tools_by_target(
    tools: Sequence[BaseTool],
    target: TargetEnv,
) -> list[BaseTool]:
    """按诊断目标过滤可用的实时采集工具。"""
    blocked = set(LOCAL_SYSTEM_TOOLS)
    blocked |= UNVERIFIED_TOOLS
    blocked |= BYPASS_TOOLS

    if target == "windows_host":
        blocked |= DOCKER_TOOLS
    elif target == "docker_container":
        blocked |= WINDOWS_TOOLS
    else:
        blocked |= WINDOWS_TOOLS
        blocked |= DOCKER_TOOLS

    return [tool for tool in tools if tool.name not in blocked]
