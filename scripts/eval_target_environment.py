"""评测：诊断目标识别准确率 + 工具隔离有效性。

为什么单独做这个评测
=====================
这个项目的核心风险不是"模型不够聪明"，而是"证据来源搞错"：
容器里的 psutil 读到的是容器，报告却写成宿主机指标，整份结论就废了。
环境隔离是纯规则实现，因此可以不调 LLM、不看随机性，逐条复现。

三个指标
--------
1. 识别准确率：detect_target_environment 与人工标注是否一致。
2. 暴露面：过滤后还剩多少"错误环境"的工具、多少"任何目标都不该出现"的工具。
3. 计划拦截：planner 是否会移除引用错误环境工具的计划步骤，且不误伤合法步骤。

用法
----
    python scripts/eval_target_environment.py            # 打印摘要 + 写报告
    python scripts/eval_target_environment.py --no-write # 只打印
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

# 评测只关心汇总；PlanGuard 每条被过滤的步骤都会打 warning，会淹没输出
logger.remove()

from app.runtime.target_environment import (  # noqa: E402
    BYPASS_TOOLS,
    DOCKER_TOOLS,
    LOCAL_SYSTEM_TOOLS,
    UNVERIFIED_TOOLS,
    WINDOWS_TOOLS,
    detect_target_environment,
    filter_tools_by_target,
)
from app.tools.meta import TOOL_META  # noqa: E402

CASES_FILE = ROOT / "benchmark" / "target_environment_cases.jsonl"
REPORT_FILE = ROOT / "benchmark" / "reports" / "target_environment_report.md"

# 任何目标下都不该出现的工具：容器内本机指标 / 位置未验证 / 可绕过过滤
ALWAYS_BLOCKED = LOCAL_SYSTEM_TOOLS | UNVERIFIED_TOOLS | BYPASS_TOOLS


def wrong_env_tools(target: str) -> set[str]:
    """该目标下属于"错误环境"的工具集合。"""
    if target == "windows_host":
        return set(DOCKER_TOOLS)
    if target == "docker_container":
        return set(WINDOWS_TOOLS)
    return set(WINDOWS_TOOLS) | set(DOCKER_TOOLS)


def required_env_tools(target: str) -> set[str]:
    """该目标下"应该保留"的环境采集工具。"""
    if target == "windows_host":
        return set(WINDOWS_TOOLS)
    if target == "docker_container":
        return set(DOCKER_TOOLS)
    return set()


def load_cases() -> list[dict]:
    cases = []
    for lineno, line in enumerate(CASES_FILE.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        item["_line"] = lineno
        cases.append(item)
    return cases


def evaluate_detection(cases: list[dict], tools: list[SimpleNamespace]) -> list[dict]:
    rows = []
    for case in cases:
        expected = case["expected"]
        detected = detect_target_environment(case["query"])
        visible = {t.name for t in filter_tools_by_target(tools, detected)}

        wrong = wrong_env_tools(detected) & set(TOOL_META)
        required = required_env_tools(detected) & set(TOOL_META)

        rows.append(
            {
                "id": case["id"],
                "query": case["query"],
                "expected": expected,
                "detected": detected,
                "correct": detected == expected,
                "note": case.get("note", ""),
                "visible_before": len(TOOL_META),
                "visible_after": len(visible),
                "wrong_env_before": len(wrong),
                "wrong_env_after": len(wrong & visible),
                "always_blocked_after": len(ALWAYS_BLOCKED & visible),
                "required_kept": required <= visible,
            }
        )
    return rows


def evaluate_plan_guard(cases: list[dict]) -> list[dict] | None:
    """检查 planner 的 sanitize_steps_for_target 是否拦截错误环境步骤。

    planner 依赖 LLM 客户端等较重的模块；导入失败时返回 None，评测降级为
    "只测识别与工具隔离"，而不是直接崩掉。
    """
    try:
        from app.agents.planner import sanitize_steps_for_target
    except Exception as exc:  # noqa: BLE001
        print(f"[skip] 无法导入 planner.sanitize_steps_for_target: {type(exc).__name__}: {exc}")
        return None

    rows = []
    for case in cases:
        target = detect_target_environment(case["query"])
        blocked = sorted(wrong_env_tools(target) | ALWAYS_BLOCKED)
        injected = [f"调用 {name} 采集数据" for name in blocked]
        legit = "调用 search_knowledge_base 检索相关 SOP"
        steps = injected + [legit, "汇总诊断结论"]

        out = sanitize_steps_for_target(steps, target)
        survived = [name for name in blocked if any(name in step for step in out)]

        rows.append(
            {
                "id": case["id"],
                "target": target,
                "injected": len(injected),
                "survived": len(survived),
                "legit_kept": any(legit in step for step in out),
                "added_windows_step": any("get_windows_host_metrics" in step for step in out),
                "naive_kept": len(set(steps)) - len(set(out)),  # 仅用于展示改动量
            }
        )
    return rows


def build_report(rows: list[dict], plan_rows: list[dict] | None, cases: list[dict]) -> str:
    total = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    wrong_before = sum(r["wrong_env_before"] for r in rows)
    wrong_after = sum(r["wrong_env_after"] for r in rows)
    blocked_after = sum(r["always_blocked_after"] for r in rows)
    env_rows = [r for r in rows if r["detected"] != "unspecified"]
    required_ok = sum(1 for r in env_rows if r["required_kept"])

    lines = [
        "# 诊断目标识别与工具隔离评测",
        "",
        f"- 数据集：`benchmark/target_environment_cases.jsonl`（{total} 条）",
        "- 运行方式：`python scripts/eval_target_environment.py`",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 工具栏：`TOOL_META` 已登记 {len(TOOL_META)} 个工具",
        "- 说明：纯规则实现，不调用 LLM，结果可逐条复现",
        "",
        "## 1. 汇总",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 目标识别准确率 | **{correct}/{total}（{correct / total:.0%}）** |",
        f"| 过滤前暴露的错误环境工具（累计） | {wrong_before} 个 |",
        f"| 过滤后暴露的错误环境工具（累计） | **{wrong_after} 个** |",
        f"| 过滤后暴露的「任何目标都不该出现」工具（累计） | **{blocked_after} 个** |",
        f"| 正确环境采集工具保留率 | **{required_ok}/{len(env_rows)}（{required_ok / len(env_rows):.0%}）** |",
        f"| 平均可见工具数（过滤前 → 过滤后） | {len(TOOL_META)} → "
        f"{sum(r['visible_after'] for r in rows) / total:.1f} |",
    ]

    if plan_rows:
        injected = sum(r["injected"] for r in plan_rows)
        survived = sum(r["survived"] for r in plan_rows)
        legit_ok = sum(1 for r in plan_rows if r["legit_kept"])
        lines += [
            f"| 计划中错误环境步骤拦截率 | **{injected - survived}/{injected}"
            f"（{(injected - survived) / injected:.0%}）** |",
            f"| 计划中合法步骤保留率 | **{legit_ok}/{len(plan_rows)}（{legit_ok / len(plan_rows):.0%}）** |",
        ]

    lines += [
        "",
        "## 2. 识别与工具隔离明细",
        "",
        "| ID | 输入（截断） | 期望 | 识别结果 | 判定 | 可见工具（前→后） | 错误环境暴露（前→后） |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        query = r["query"].replace("|", "\\|")
        query = query if len(query) <= 26 else query[:26] + "…"
        lines.append(
            f"| {r['id']} | {query or '(空)'} | {r['expected']} | {r['detected']} | "
            f"{'✅' if r['correct'] else '❌'} | {r['visible_before']} → {r['visible_after']} | "
            f"{r['wrong_env_before']} → **{r['wrong_env_after']}** |"
        )

    if plan_rows:
        lines += [
            "",
            "## 3. 计划侧拦截（sanitize_steps_for_target）",
            "",
            "对每条用例注入“调用每个被禁工具”的计划步骤，检查是否被移除、合法步骤是否被误伤。",
            "",
            "| ID | 目标 | 注入非法步骤 | 存活 | 合法步骤保留 | 自动补 Windows 采集 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for r in plan_rows:
            lines.append(
                f"| {r['id']} | {r['target']} | {r['injected']} | **{r['survived']}** | "
                f"{'✅' if r['legit_kept'] else '❌'} | {'✅' if r['added_windows_step'] else '—'} |"
            )

    failed = [r for r in rows if not r["correct"]]
    lines += ["", "## 4. 结论与已知局限", ""]
    if failed:
        lines += [
            f"- 识别失败 {len(failed)} 条：" + "、".join(f"`{r['id']}`（期望 {r['expected']}，"
            f"实际 {r['detected']}）" for r in failed),
            "- 失败方向需要人工确认：`unspecified` 属于保守降级（少采集但不会误采），"
            "误判成 `windows_host` / `docker_container` 才是危险方向。",
        ]
    else:
        lines.append("- 全部用例识别正确；负向用例（否定/对照/双目标）均未误判成单一目标。")
    lines += [
        "- 隔离是**工具可见性**级别的硬约束：即使模型被提示词诱导，也拿不到错误环境的工具；"
        "计划侧过滤只是第二道软约束（按工具名匹配文本，换说法会漏）。",
        "- 数据集规模 25 条，覆盖的是规则设计时考虑过的句式；真实流量的口语分布更杂，"
        "结论只能说明“已知风险句式被覆盖”，不能外推为线上准确率。",
        "- 未覆盖：多轮对话中途改目标、告警 payload 自带 `labels.instance` 的平台推断。",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    cases = load_cases()
    tools = [SimpleNamespace(name=name) for name in TOOL_META]
    rows = evaluate_detection(cases, tools)
    plan_rows = evaluate_plan_guard(cases)

    report = build_report(rows, plan_rows, cases)
    if "--no-write" not in argv:
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(report, encoding="utf-8")

    correct = sum(1 for r in rows if r["correct"])
    wrong_after = sum(r["wrong_env_after"] for r in rows)
    blocked_after = sum(r["always_blocked_after"] for r in rows)
    print(f"cases={len(rows)}  accuracy={correct}/{len(rows)}")
    print(f"wrong_env_exposed={wrong_after}  always_blocked_exposed={blocked_after}")
    if plan_rows:
        injected = sum(r["injected"] for r in plan_rows)
        survived = sum(r["survived"] for r in plan_rows)
        print(f"plan_steps_injected={injected}  survived={survived}  "
              f"legit_kept={sum(1 for r in plan_rows if r['legit_kept'])}/{len(plan_rows)}")
    if "--no-write" not in argv:
        print(f"report -> {REPORT_FILE.relative_to(ROOT)}")
    return 0 if correct == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
