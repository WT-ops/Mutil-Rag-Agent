# 诊断目标识别与工具隔离评测

- 数据集：`benchmark/target_environment_cases.jsonl`（25 条）
- 运行方式：`python scripts/eval_target_environment.py`
- 生成时间：2026-10-27 16:37
- 工具栏：`TOOL_META` 已登记 27 个工具
- 说明：纯规则实现，不调用 LLM，结果可逐条复现

## 1. 汇总

| 指标 | 数值 |
| --- | --- |
| 目标识别准确率 | **25/25（100%）** |
| 过滤前暴露的错误环境工具（累计） | 88 个 |
| 过滤后暴露的错误环境工具（累计） | **0 个** |
| 过滤后暴露的「任何目标都不该出现」工具（累计） | **0 个** |
| 正确环境采集工具保留率 | **16/16（100%）** |
| 平均可见工具数（过滤前 → 过滤后） | 27 → 17.5 |
| 计划中错误环境步骤拦截率 | **238/238（100%）** |
| 计划中合法步骤保留率 | **25/25（100%）** |

## 2. 识别与工具隔离明细

| ID | 输入（截断） | 期望 | 识别结果 | 判定 | 可见工具（前→后） | 错误环境暴露（前→后） |
| --- | --- | --- | --- | --- | --- | --- |
| W01 | 请诊断我当前 Windows 宿主机的内存使用情况。… | windows_host | windows_host | ✅ | 27 → 17 | 4 → **0** |
| W02 | 诊断 Windows 宿主机的内存，Docker 容… | windows_host | windows_host | ✅ | 27 → 17 | 4 → **0** |
| W03 | 分析 Windows 11 的内存使用情况 | windows_host | windows_host | ✅ | 27 → 17 | 4 → **0** |
| W04 | 排查我的笔记本内存异常 | windows_host | windows_host | ✅ | 27 → 17 | 4 → **0** |
| W05 | 帮我看看 Windows 的内存 | windows_host | windows_host | ✅ | 27 → 17 | 4 → **0** |
| W06 | diagnose windows host memo… | windows_host | windows_host | ✅ | 27 → 17 | 4 → **0** |
| W07 | 诊断我电脑的 CPU 占用，不要用容器里的数据 | windows_host | windows_host | ✅ | 27 → 17 | 4 → **0** |
| W08 | 我电脑很卡，检查 CPU、内存、磁盘和高占用进程 | windows_host | windows_host | ✅ | 27 → 17 | 4 → **0** |
| W09 | 先不要看容器，诊断 Windows 宿主机的磁盘 | windows_host | windows_host | ✅ | 27 → 17 | 4 → **0** |
| D01 | 检查 Docker 容器内存，不要使用 Window… | docker_container | docker_container | ✅ | 27 → 20 | 1 → **0** |
| D02 | 诊断我电脑上的 Docker 容器内存 | docker_container | docker_container | ✅ | 27 → 20 | 1 → **0** |
| D03 | 不要检查 Windows 宿主机，改为诊断 Dock… | docker_container | docker_container | ✅ | 27 → 20 | 1 → **0** |
| D04 | 查询 docker_stats 对应的 Docker… | docker_container | docker_container | ✅ | 27 → 20 | 1 → **0** |
| D05 | 检查 Docker 容器内存，Windows 宿主机… | docker_container | docker_container | ✅ | 27 → 20 | 1 → **0** |
| D06 | 诊断 Docker 容器而不是 Windows 宿主… | docker_container | docker_container | ✅ | 27 → 20 | 1 → **0** |
| D07 | check docker container mem… | docker_container | docker_container | ✅ | 27 → 20 | 1 → **0** |
| U01 | 比较 Windows 宿主机和 Docker 容器的… | unspecified | unspecified | ✅ | 27 → 16 | 5 → **0** |
| U02 | 同时诊断 Windows 宿主机和 Docker 容… | unspecified | unspecified | ✅ | 27 → 16 | 5 → **0** |
| U03 | 诊断 Windows 宿主机和 Docker 容器的… | unspecified | unspecified | ✅ | 27 → 16 | 5 → **0** |
| U04 | 检查 PostgreSQL 连接池 | unspecified | unspecified | ✅ | 27 → 16 | 5 → **0** |
| U05 | 诊断宿主机内存 | unspecified | unspecified | ✅ | 27 → 16 | 5 → **0** |
| U06 | (空) | unspecified | unspecified | ✅ | 27 → 16 | 5 → **0** |
| U07 | 不要诊断 Windows 宿主机和 Docker 容… | unspecified | unspecified | ✅ | 27 → 16 | 5 → **0** |
| U08 | Redis 实例 redis-master-01 内… | unspecified | unspecified | ✅ | 27 → 16 | 5 → **0** |
| U09 | 帮我看看磁盘是不是满了 | unspecified | unspecified | ✅ | 27 → 16 | 5 → **0** |

## 3. 计划侧拦截（sanitize_steps_for_target）

对每条用例注入“调用每个被禁工具”的计划步骤，检查是否被移除、合法步骤是否被误伤。

| ID | 目标 | 注入非法步骤 | 存活 | 合法步骤保留 | 自动补 Windows 采集 |
| --- | --- | --- | --- | --- | --- |
| W01 | windows_host | 10 | **0** | ✅ | ✅ |
| W02 | windows_host | 10 | **0** | ✅ | ✅ |
| W03 | windows_host | 10 | **0** | ✅ | ✅ |
| W04 | windows_host | 10 | **0** | ✅ | ✅ |
| W05 | windows_host | 10 | **0** | ✅ | ✅ |
| W06 | windows_host | 10 | **0** | ✅ | ✅ |
| W07 | windows_host | 10 | **0** | ✅ | ✅ |
| W08 | windows_host | 10 | **0** | ✅ | ✅ |
| W09 | windows_host | 10 | **0** | ✅ | ✅ |
| D01 | docker_container | 7 | **0** | ✅ | — |
| D02 | docker_container | 7 | **0** | ✅ | — |
| D03 | docker_container | 7 | **0** | ✅ | — |
| D04 | docker_container | 7 | **0** | ✅ | — |
| D05 | docker_container | 7 | **0** | ✅ | — |
| D06 | docker_container | 7 | **0** | ✅ | — |
| D07 | docker_container | 7 | **0** | ✅ | — |
| U01 | unspecified | 11 | **0** | ✅ | — |
| U02 | unspecified | 11 | **0** | ✅ | — |
| U03 | unspecified | 11 | **0** | ✅ | — |
| U04 | unspecified | 11 | **0** | ✅ | — |
| U05 | unspecified | 11 | **0** | ✅ | — |
| U06 | unspecified | 11 | **0** | ✅ | — |
| U07 | unspecified | 11 | **0** | ✅ | — |
| U08 | unspecified | 11 | **0** | ✅ | — |
| U09 | unspecified | 11 | **0** | ✅ | — |

## 4. 结论与已知局限

- 全部用例识别正确；负向用例（否定/对照/双目标）均未误判成单一目标。
- 隔离是**工具可见性**级别的硬约束：即使模型被提示词诱导，也拿不到错误环境的工具；计划侧过滤只是第二道软约束（按工具名匹配文本，换说法会漏）。
- 数据集规模 25 条，覆盖的是规则设计时考虑过的句式；真实流量的口语分布更杂，结论只能说明“已知风险句式被覆盖”，不能外推为线上准确率。
- 未覆盖：多轮对话中途改目标、告警 payload 自带 `labels.instance` 的平台推断。
