# 单元测试

```bash
pip install -r requirements-dev.txt
pytest -q
```

## 设计约束

1. **不连任何外部服务**：Milvus / Redis / Postgres / LLM Provider 一律不碰。
   检索融合用假 BM25 索引，工具过滤用假 Skill Registry，队列只测纯函数映射。
2. **不花冤枉钱**：`conftest.py` 把 Provider Key 覆盖成占位符，
   即使本地有 `.env` 也不会真的发出付费请求。
3. **锁的是"决策"不是"实现"**：权限矩阵、工具可见性、证据判定、RRF 排序、
   环境识别这些一旦被改坏，测试立刻红。

## 覆盖范围

| 文件 | 锁住什么 |
| --- | --- |
| `test_permissions.py` | 三态权限矩阵（allow/ask/deny）、Layer 顺序、模式解析容错 |
| `test_tool_filter.py` | 谁能被 LLM 看见、只读自动补白名单、deny 永不暴露 |
| `test_tool_meta.py` | ToolMeta fail-closed 默认、输入感知只读、高危集合派生 |
| `test_target_environment.py` | 13 条歧义问法的目标识别 + 工具隔离不变量 |
| `test_tool_evidence.py` | 只有 ToolMessage 算证据、失败前缀、未记录工具检测 |
| `test_hybrid_rrf.py` | RRF 排序语义、两路去重、BM25 不可用时的降级 |
| `test_incident_signature.py` | 告警指纹稳定性（跨实例/跨时间同类聚合） |
| `test_queue_priority.py` | severity/priority → 队列级别映射与脏数据降级 |
| `test_security_invariants.py` | 禁止 bypass 默认、`.env` 不入库、无真实密钥 |

## 已知缺口（下一步）

- 权限矩阵里 `ASK_DESTRUCTIVE` 对"非 destructive 的写工具"（如 `mcp_execute_tool`）
  不会触发审批，当前断言记录的是现状，属于待修复项。
- deep 诊断链路尚未接入 `PermissionMode` 与 `tool_evidence`，两条链路证据标准不一致。
- `agent_harness.build_report_messages` 的 prompt 断言需要完整依赖，暂未纳入。
