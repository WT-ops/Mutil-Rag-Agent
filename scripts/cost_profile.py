"""成本画像：估算一次 fast 链诊断的 LLM 调用次数与 prompt tokens。

为什么不用 tiktoken：它需要联网下载词表，离线环境不可用。
这里用字符级启发式估算（中文 0.75 token/字、英文 1.3 token/词），误差约 ±20%，
只用于"量级判断"，不用于计费。

用法：
    python scripts/cost_profile.py
    python scripts/cost_profile.py --price-per-mtok 2.0
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.runtime.agent_harness import get_agent_harness  # noqa: E402
from app.skills.registry import get_skill_registry  # noqa: E402
from app.tools.meta import TOOL_META  # noqa: E402

CJK = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD = re.compile(r"[A-Za-z0-9_]{2,}")
PUNCT = re.compile(r"[，。；：、！？（）「」【】…—·]")

# 三个典型输入：简单本机问题 / 容器告警 / 宿主机内存
CASES = [
    ("简单（本机）", "我电脑很卡，帮我看看 CPU 和内存"),
    ("容器告警", "Redis 实例 redis-master-01 内存使用率 98%，客户端连接被强制断开"),
    ("宿主机内存", "诊断我当前 Windows 宿主机的内存使用情况，区分 Docker 容器"),
]

PLAN = [
    "调用 get_windows_host_metrics 获取 Windows 主机 CPU、内存和进程数据",
    "核对返回值中的 source/os 与采样时间，标注仍缺失的指标",
    "汇总诊断结论，区分真实证据和推测",
]
PAST_STEPS = [
    (PLAN[0], "已获取内存 15.86GB、可用 3.2GB、Top 进程 5 个。"),
    (PLAN[1], "source=windows_host, os=Windows，未返回磁盘与 GPU 指标。"),
]
EVIDENCE = [
    {"tool_name": "get_windows_host_metrics", "status": "returned",
     "iteration": 1, "result": '{"source":"windows_host","os":"Windows","memory":{"used_percent":79.6}}'},
]


def estimate_tokens(text: str) -> int:
    """字符级启发式：中文按 0.75 token/字，英文按 1.3 token/词，标点按 0.9。"""
    cjk = len(CJK.findall(text))
    words = len(ASCII_WORD.findall(text))
    punct = len(PUNCT.findall(text))
    return max(1, round(cjk * 0.75 + words * 1.3 + punct * 0.9))


def messages_tokens(messages: list[dict]) -> int:
    return sum(estimate_tokens(str(m.get("content") or "")) for m in messages)


def tool_schema_tokens(skill_name: str) -> int:
    """估算 bind_tools 时注入的工具声明大小（name + search_hint）。"""
    registry = get_skill_registry()
    skill = registry.get_or_generic(skill_name)
    total = 0
    for name in skill.allowed_tools:
        meta = TOOL_META.get(name)
        total += estimate_tokens(name)
        if meta and meta.search_hint:
            total += estimate_tokens(meta.search_hint)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIOps fast 链成本画像（静态估算）")
    parser.add_argument("--price-per-mtok", type=float, default=2.0,
                        help="示例单价，元/百万 token（按你实际用的模型填）")
    parser.add_argument("--steps", type=int, default=3, help="按几步诊断估算")
    args = parser.parse_args(argv)

    harness = get_agent_harness()
    registry = get_skill_registry()
    skill = registry.get_or_generic("host_resource_diagnosis")

    per_case: list[tuple[str, dict[str, int]]] = []
    for label, user_input in CASES:
        router = messages_tokens(
            harness.build_skill_router_messages(
                menu=registry.to_router_menu(),
                user_input=user_input,
                generic="generic_oncall",
                lessons="",
            )
        )
        planner = messages_tokens(
            harness.build_planner_messages(
                user_input=user_input,
                skill_display_name=skill.display_name,
                skill_playbook=skill.playbook,
            )
        )
        executor_sys = estimate_tokens(harness.executor_system_prompt())
        executor = executor_sys + estimate_tokens(
            harness.build_executor_task_prompt(
                plan=PLAN, step_index=1, total_steps=len(PLAN), current_step=PLAN[0]
            )
        ) + tool_schema_tokens(skill.name)

        replanner = messages_tokens(
            harness.build_replanner_messages(
                user_input=user_input,
                current_time="2026-11-10 15:00:00",
                current_skill_line=f"当前 Skill: {skill.name}",
                candidate_skills_text="host_resource_diagnosis / network_diagnosis",
                tried_skills_text="无",
                reroute_count=0,
                reroute_quota_hint="",
                plan_text="\n".join(PLAN),
                past_steps_text="\n".join(f"{s} -> {r}" for s, r in PAST_STEPS),
            )
        )
        report = messages_tokens(
            harness.build_report_messages(
                user_input=user_input,
                past_steps=PAST_STEPS,
                current_time="2026-11-10 15:00:00",
                draft="（草稿）",
                tool_evidence=EVIDENCE,
            )
        )
        per_case.append(
            (label, {"router": router, "planner": planner, "executor": executor,
                     "replanner": replanner, "report": report})
        )

    nodes = ["router", "planner", "executor", "replanner", "report"]
    print("## 各节点 prompt tokens（启发式估算，±20%）\n")
    print("| 输入 | " + " | ".join(nodes) + " |")
    print("| --- | " + " | ".join("---" for _ in nodes) + " |")
    for label, data in per_case:
        print(f"| {label} | " + " | ".join(str(data[n]) for n in nodes) + " |")

    # 调用次数模型：router 1 + planner 1 + executor n + replanner n + report 1 = 2n + 3
    print("\n## 单次诊断的总量（按 3 步计划）\n")
    print("| 输入 | LLM 调用次数 | prompt tokens | 估算成本（元） |")
    print("| --- | --- | --- | --- |")
    totals = []
    for label, data in per_case:
        calls = 1 + 1 + args.steps + args.steps + 1
        total = (data["router"] + data["planner"] + data["report"]
                 + args.steps * data["executor"] + args.steps * data["replanner"])
        cost = total / 1_000_000 * args.price_per_mtok
        totals.append(total)
        print(f"| {label} | {calls} | {total:,} | {cost:.4f} |")

    avg = round(statistics.mean(totals))
    low, high = round(avg * 0.8), round(avg * 1.2)
    print(f"\n**平均：约 {args.steps * 2 + 3} 次调用、{avg:,} prompt tokens"
          f"（区间 {low:,}–{high:,}）**")

    print("\n## 可写进简历的一句话\n")
    print(f"> 对单次诊断做成本画像：平均约 {args.steps * 2 + 3} 次 LLM 调用、"
          f"{avg // 1000}k–{high // 1000}k prompt tokens（字符级估算，±20%），"
          f"为「何时路由到 deep 链」提供成本依据。")

    print("\n> 说明：本脚本不调用任何模型，仅统计 prompt 长度；"
          "tiktoken 需联网下载词表，离线环境不可用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
