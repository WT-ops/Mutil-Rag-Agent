---
name: host_resource_diagnosis
display_name: 主机资源诊断 (CPU/内存/磁盘)
description: 本机或主机 CPU 高、内存高/OOM、磁盘满、系统卡顿、风扇响等资源类故障。先确认诊断目标及监控工具的真实数据来源，再按 CPU / 内存 / 磁盘分支进行证据驱动诊断。
triggers:
  # 本机词 (吸收原 local_machine_diagnosis)
  - 我的电脑
  - 我电脑
  - 我的笔记本
  - 我笔记本
  - 本机
  - 这台电脑
  - 这台机器
  - 自己的电脑
  - 我的机器
  - 本地电脑
  - 本地机器
  - localhost
  - my computer
  - my laptop
  - my pc
  - Windows 宿主机
  - Windows 主机
  # CPU 词 (吸收原 cpu_high_usage)
  - cpu 高
  - cpu 100
  - cpu 使用率
  - cpu 持续高
  - load average
  - 负载高
  - 主机变慢
  - 电脑卡
  - 风扇响
  # 内存词 (吸收原 memory_high_usage)
  - 内存高
  - 内存使用率
  - 内存占用
  - oom
  - oomkilled
  - memory leak
  - 内存泄漏
  - 内存满
  - 内存爆
  # 磁盘词 (吸收原 disk_full)
  - 磁盘满
  - 磁盘使用率
  - disk full
  - no space left
  - 磁盘告警
  - inode 满
  - 没空间
allowed_tools:
  - search_knowledge_base
  - get_current_time
  - get_local_system_overview
  - get_local_cpu_memory
  - get_local_disk_usage
  - list_top_processes
  - query_windows_event
  - web_search
  - get_windows_host_metrics
risk_level: low
---

# 主机资源诊断 Playbook

## 适用场景
- 主机/容器 CPU 持续 >80% 或 load 异常
- 主机/容器内存 >85%、频繁 OOMKilled、进程 RSS 持续上涨疑似泄漏
- 磁盘使用率 >80%、inode 用尽、`No space left on device`
- 用户报告“我电脑/我笔记本/本机”卡顿、风扇响、崩溃、无空间等资源类问题
- 告警内容包含 cpu_high / load_high / memory_high / oom / disk_full / pod restart

**不适用**：纯网络问题走 `network_diagnosis`；明确的容器级故障（容器挂了、重启循环）走 `container_diagnosis`。用户明确诊断 Windows 宿主机，即使要求区分 Docker 容器，也仍属于本 Skill。

## 数据来源约束（必须遵守）
- **不同工具的数据来源不同，不能笼统宣称“全部来自本机 psutil”。** Windows 专用工具 `get_windows_host_metrics` 在 Windows 主机上采样；`get_local_*` 等 psutil 工具在当前 Docker API 部署中采集的是容器运行环境，不是 Windows 宿主机；Docker 专用工具则面向指定容器。
- 仅当调用结果中明确出现 `source=windows_host` 且 `os=Windows` 时，才可把对应测量值标注为 Windows 宿主机数据。实际采样时间以工具返回为准；如果未返回采样时间，说明“未提供”，不要把报告生成时间当成采样时间。
- 工具成功加载、Planner 提及工具名、Executor 文字摘要，都不等于工具已经被实际调用。只把实际工具返回记录视为调用证据；`status=returned` 只表示工具返回，并不代表独立核验结果正确。
- 不得编造未采集的指标、趋势、事件日志、OOM 记录及根因。知识库 (`search_knowledge_base`) 仅作通用排查思路参考，不能作为当前主机现状的证据。
- 此 Skill 的 `allowed_tools` 保留原有兼容工具声明，但实际可调用集合必须服从 Executor 的目标环境过滤：在当前 Docker API 部署下，`get_local_*`、`list_top_processes` 和容器内的 `query_windows_event` 不得冒充 Windows 主机采集工具。

### Windows 主机诊断约束
- 用户明确要求诊断 Windows 主机、Windows 电脑或自己的 Windows 笔记本时，必须优先调用 `get_windows_host_metrics`。
- 如果 Windows MCP 不可用或无成功返回记录，明确表示无法获取实时指标，不能用 Docker 容器的数据代替。
- 当前 Windows 工具主要提供 CPU、内存与 Top 进程；不要据此编造磁盘、GPU、事件日志、分页错误率或历史趋势。
- 进程的工作集、RSS 与系统总内存使用量是不同口径，不要简单累加进程内存并宣称完整解释了系统内存占用。

## Phase 1: 先拍快照（必做）
1. 确认**诊断目标环境**：Windows 宿主机使用 `get_windows_host_metrics`；明确诊断 Docker 容器使用对应容器监控工具；仅在采集进程与目标环境真正一致时才可使用本地 psutil 工具。
2. 最少采集一份有效快照并核对 `source`、`os`、实际指标及采样时间（如返回）。已获取有效数据时无需为了凑步骤重复调用；怀疑趋势异常时可以计划有时间间隔的复测，但要清楚说明复测目的。
3. 根据用户报告和实际可用指标选择分支：CPU 走 Phase 2-A；内存/OOM 走 Phase 2-B；磁盘走 Phase 2-C。对未采集的维度直接标明“无法核验”，不要代填数值。

## Phase 2-A: CPU 分支
1. Windows 主机：优先查看 `get_windows_host_metrics` 实际返回的 CPU 指标；没有分核心或历史 CPU 指标时，不得编造。
2. 其他环境：仅在当前监控工具与诊断目标一致且可用时，使用 `get_local_cpu_memory` 和 `list_top_processes(sort_by=cpu)`。Docker 容器优先使用与容器相匹配的监控工具，并以实际工具可用性为准。
3. 区分**已观测的瞬时使用率**与“稳态高/周期性尖峰/多核持续高”。后几种形态通常需要多次采样或历史曲线证明，不能凭单点推断死循环、I/O wait 或 GC 原因。
4. 当前部署下 `query_windows_event` 不具备可信的 Windows 主机采集来源，不应作为 Windows 事件实测证据；需要时说明该数据尚未获取。

## Phase 2-B: 内存分支

### Windows 主机内存诊断（优先规则）
1. 使用 `get_windows_host_metrics` 获取 Windows 宿主机总内存、已用/可用、使用率以及工具真实提供的 Top 进程；核对 `source=windows_host` 与 `os=Windows`。
2. 已返回内存与进程数据时，不要重复调用被隔离的 `get_local_cpu_memory`、`get_local_system_overview`、`list_top_processes`，也不得使用容器指标冒充 Windows 宿主机指标。
3. **内存占用不等于故障**：单次 70%～85% 左右的使用率是状态信息，不能仅凭百分比确诊异常；需结合可用内存、性能问题、OOM/提交压力、持续时间或用户症状。
4. **禁止直接归因**：单次采样不能证明泄漏、持续上涨或某进程造成所有内存压力。即使 `vmmemWSL` 或类似 WSL2 进程排名靠前，也只能说明它占用了一部分内存，不能直接称其为根本原因。
5. `MemCompression` 是 Windows 正常内存管理机制的一部分。占用较高不等于存在内存压缩故障；需有额外的分页/性能异常证据才能进一步判断。
6. Windows 总内存使用率与各进程工作集属于不同统计口径；不能用进程 RSS 求和作为根因归属证明。
7. 对可能原因明确标记 **“已确认”/“可能”/“待验证”**，并写清还缺少何种证据。
8. **禁止建议在没有停机计划时立即执行 `wsl --shutdown`**。该命令可能中断 WSL2、Docker Desktop、数据库以及依赖这些服务的应用；不得将其包装为安全、零成本的“紧急止损”。
9. 在未确认 Docker/WSL 工作负载的内存预算、峰值需求和恢复方案前，不得建议将 `.wslconfig` 的 `memory=2GB`、`swap=0` 作为通用优化方案。
10. 需要停机、重启、修改系统配置等操作时，必须事先列出影响对象、维护窗口、备份/恢复和用户批准条件；不得自主执行。

### 其他环境内存诊断
1. 必须先确认目标环境与工具运行环境一致；Docker 容器诊断优先使用容器专用工具（如 `docker_stats`）。
2. Docker API 内部的本地监控数据不得作为 Windows 物理主机指标。
3. 未确认监控来源时只提供通用只读排查方案，明确说明缺少实时证据。

### 内存问题判断原则
- 稳态高：可能是缓存、常驻服务或正常工作负载，需要历史数据才能确认“稳态”。
- 持续上涨：可能存在内存泄漏，必须结合有时间间隔的多次采样或历史曲线验证。
- 伴随 OOMKilled：必须有容器事件、日志或有效监控证据，不能凭空声称发生。
- 内存压缩较高：不能仅凭单次快照判断故障。
- 进程占用居前：只表示单次排序事实，不等于该进程是故障根因。

## Phase 2-C: 磁盘分支
1. Windows 宿主机：当前 `get_windows_host_metrics` 未保证提供磁盘数据；若没有经验证的 Windows 磁盘采集工具，应如实说明“磁盘指标未采集”，不要调用容器的 `get_local_disk_usage` 冒充 Windows 磁盘。
2. 其他环境：仅在目标环境一致且工具实际可用时，调用 `get_local_disk_usage` 查看分区与 inode；Docker 容器使用对应的容器或卷监控渠道。
3. 空间用尽可能需要定位日志、临时目录等；inode 用尽可能涉及大量小文件；持有已删除文件等情形必须有文件句柄/磁盘证据，不能凭空认定。
4. 不建议不经核实就执行 `rm`、`truncate`、删除日志或重启进程；这些操作可能导致数据丢失或服务中断，应先做只读确认并经用户批准。

## Phase 3: 输出报告
按五段式输出：**问题概述、关键证据、根因分析、处置建议、结论**。

- **问题概述**：区分用户报告的现象与实际监控状态，不把一次偏高读数直接定义为故障。
- **关键证据**：只列实际工具返回的值，注明工具名、`source`、`os`、采样时间（若提供）和单位。失败工具不能写成成功调用。
- **根因分析**：分成“已测事实 / 候选解释 / 待验证证据”；当前证据不足时明确写 **“根因未确认”**，不得将 `vmmemWSL`、`MemCompression` 等高占用进程直接指定为主因。
- **处置建议**：必须包含“紧急止损 / 长期优化”两小节，但如果没有真实故障和紧迫性证据，“紧急止损”应写 **“暂无证据支持立即停机、重启或修改配置；优先只读复核”**。长期优化应附前置条件和风险说明。
- **结论**：用一句话说明当前可确认的状态和尚未确定的因果关系；不宣称未采集到的趋势、日志或阈值告警。

## 注意事项
- 真实采集 ≠ 数值独立验证；模型总结、计划文本和知识库不能替代实际工具证据。
- 所有写操作（kill / restart / 扩容 / 删除文件 / 停止 WSL / 改 `.wslconfig`）都不能自主执行。需要先确认风险、维护窗口、回滚方案和用户授权。
- 运行中的 Docker Desktop、Milvus、PostgreSQL 和 MCP 服务可能依赖 WSL2；切勿以释放内存为由直接建议 `wsl --shutdown` 或极低 WSL 内存上限。
- 内存泄漏需看趋势；单点高使用率不等于泄漏。缺少数据时诚实说明诊断限制。
