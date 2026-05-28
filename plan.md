# EGM Execution Plan

Date: 2026-05-28

## 这份 plan.md 的作用

这是 EGM 后续开发的唯一主蓝本。它已经吸收并取代早期的状态交接、Codex 注意事项和未来路线文档。

以后判断“下一步做什么”，只看这个文件。  
以后判断“能不能发 v0.5 / v1.0”，也看这个文件。

---

## 产品定位与边界

EGM 的最高定位：

> Evidence-Gated Memory 是一个面向 hard-anchor 企业 Agent 的证据门控图记忆 Python library。

它要解决的不是“让 Agent 记住更多聊天内容”，而是让 Agent 在订单、工单、退款、合规、财务、代码修复这类高风险流程里，只能把有证据、未过期、可追溯、可审计的结论提升为事实，并把当前任务状态维护成可恢复的图结构。

核心产品形态：

- 首要形态：可 `pip install` 的 Python library。
- 核心用户：正在写业务 Agent / workflow Agent 的开发者。
- 核心场景：有明确 anchor 的企业任务，例如 `order_id`、`ticket_id`、`case_id`、`pull_request_id`、`invoice_id`。
- 核心能力：refs 原始证据、evidence gate、freshness、derived fact cascade、TaskGraph、Mermaid projection、audit log、context builder。
- 成熟方向：让 EGM 更容易接入现有 agent loop，而不是自己变成通用 Agent 框架。

明确不是：

- 不是通用聊天机器人长期记忆。
- 不是替代 Mem0 / Zep / Letta 的全栈 persona memory 平台。
- 不是向量数据库。
- 不是 hosted service。
- 不是 workflow orchestration 框架。
- 不是 UI-first 产品。

未来可以扩展服务化、Postgres、向量插件、UI viewer，但这些都必须建立在 core library 成熟之后，不能反过来主导项目方向。

---

## 标准使用路径

外部开发者最终应该这样使用 EGM：

1. 安装：`pip install evidence-gated-memory`。
2. 选择或编写 domain schema，例如 refund、ticket、coding、compliance。
3. 工具调用、API 返回、测试日志先进入 `record_evidence()`，保存 refs 原始证据。
4. Agent 想声明业务结论时调用 `assert_fact()`。
5. gate 接受时，事实进入 Fact Layer；gate 拒绝时，返回缺少什么、为什么缺、下一步该补什么。
6. 长任务用 TaskGraph / TaskNode 维护业务节点状态。
7. 生产路径使用 `transition_node()`，不能直接把节点标为 done。
8. 每次调用 LLM 前用 `build_context()` 注入 gated facts、task map、freshness、blocked reason、long-term memory。
9. 如果使用 LangChain / LangGraph / OpenAI Agents，adapter 只负责把这些步骤接到对应 agent loop 里，不改变 EGM 的证据规则。

这条使用路径决定了后续 roadmap 的优先级：先让本地 library 跑通、讲清楚、测可信，再做 adapter；先做 adapter，再考虑服务化和 UI。

---

## 当前项目状态

EGM 当前已经不是空壳项目，而是一个已发布到 PyPI 的 alpha Python library。

已完成：

- evidence / claim / fact / gate 主链路
- strict schema：未知 evidence type / claim type 会被拒绝
- source system allowlist
- freshness：fresh / stale / expired
- derived fact cascading invalidation
- audit log
- TaskGraph / TaskNode / TaskEdge
- Mermaid projection
- `transition_node()` gated state API
- refs 原始证据层
- offload JSONL mid-layer index
- L0 / L1 / L2 / L3 manual semantic pyramid
- `build_context()` 注入 TaskGraph + gated facts + L1-L3 memory
- tau-bench / tau2-bench batch runner 初步可跑
- PyPI `evidence-gated-memory` v0.4.0 已发布

当前主要短板：

- benchmark 叙事还需要统一和可复现化
- demo 还不够短、不够强、不够容易传播
- README 第一屏仍然偏重架构，不够“10 秒懂”
- migration runner 还不是正式体系
- LangChain / LangGraph / OpenAI Agents 接入还不够成熟
- production guide、audit export、observability 还不完整
- 企业级并发、retention、normalized storage 还只是设计债

---

## 不变量：开发时不能破坏的底线

这些来自早期 handoff 讨论，已经收敛进本文件。后续不再维护单独的 handoff 文档。

1. `update_task_node_status()` 是低层 CRUD，不走 gate。
2. 生产路径必须使用 `transition_node()`，状态转换必须可被 gate 拒绝。
3. facts 不能绕过 gate 写入。
4. `commit_fact()` 必须拿到有效 `GateResult`。
5. `attach_evidence_to_node()` 和 `attach_fact_to_node()` 必须验证目标存在。
6. invalidated fact 不能被 attach 到 TaskNode。
7. TaskNode 粒度是业务节点，不是每条 message，也不是每次 tool call。
8. Mermaid 是 projection，不是 source of truth。
9. Every TaskNode / Task / Edge mutation must write audit.
10. LLM entity extraction 只能是 low-trust annotation，不能作为 fact grounding。
11. Automatic L0 to L1 distillation 继续 defer，不能顺手塞进去。
12. 新 FTS 查询路径必须经过安全 sanitize，并保留 fallback。
13. schema migration 必须显式处理，不能继续只靠 `CREATE TABLE IF NOT EXISTS`。

---

## 总路线

项目接下来分成五个阶段：

| 阶段 | 名称 | 目标 | 版本出口 |
|---|---|---|---|
| Phase 0 | Truth & Safety | 把当前状态、benchmark、凭据、README 说法收干净 | v0.4.x patch |
| Phase 1 | Credible Alpha | 让外部用户能看懂、跑通、相信 | v0.5 |
| Phase 2 | Adapter Beta | 让别人能接到自己的 agent loop | v0.7 |
| Phase 3 | Production Foundation | 让长期 workspace、升级、审计、基本并发可控 | v0.8 / v0.9 |
| Phase 4 | Professional Library | 达到专业 Python library 的 v1.0 标准 | v1.0 |

---

## 当前下一步

如果现在只做一件事，做：

> Phase 0：Truth & Safety

原因：

- 项目已经公开，最怕 README / benchmark / 实际代码不一致。
- benchmark 是外部信任入口，必须先收口。
- 之前已经发现过 hardcoded API key，这类问题必须归零。
- 没有清楚 demo 和 benchmark，再加功能对 star 和采用帮助有限。

Phase 0 完成后，才能进入 v0.5 的 demo 和 README 主攻。

---

## Phase 0：Truth & Safety

目标：当前 repo 对外说法可信、没有明显安全问题、benchmark 和代码状态一致。

### P0-01：安全扫描和凭据清理

状态：部分完成。`benchmarks/tau_bench/run_ab.py` 的 hardcoded key 已清理，但需要全仓复核。

依赖：无。

交付：

- 全仓扫描 `sk-`、API key、token、个人路径。
- benchmark 脚本只读环境变量。
- 提供 `.env.example`。
- README benchmark 部分说明如何设置 `DEEPSEEK_API_KEY`。

验收：

- `benchmarks/`、`examples/`、`docs/` 中没有 hardcoded secret。
- 没有默认 API key fallback。
- 没有把个人路径当成用户默认路径。

解锁：

- P0-02 benchmark 叙事统一。
- P1 demo 对外截图。

### P0-02：benchmark 叙事统一

依赖：P0-01。

交付：

- 更新 README benchmark 段落。
- 更新 `reports/benchmark_report.md`。
- 明确三类结果：
  - deterministic local benchmarks
  - official-data retrieval proxy
  - downstream agent A/B benchmark

验收：

- 不把 retrieval proxy 写成 official leaderboard。
- 不把 3-task / 8-task smoke 写成完整 pass@k。
- tau-bench、tau2-bench、MemoryAgentBench 当前状态一致。

解锁：

- P0-03 benchmark snapshot。
- P1 README 第一屏重写。

### P0-03：benchmark snapshot 生成器

依赖：P0-02。

交付：

- 一个脚本生成：
  - `reports/benchmark_snapshot_YYYY-MM-DD.json`
  - `reports/benchmark_snapshot_YYYY-MM-DD.md`
- 汇总 local probes、scenario probes、MemoryAgentBench、tau-bench、tau2-bench。

验收：

- 每条结果都有：
  - data size
  - metric
  - score
  - interpretation
  - limitation
- 运行失败时给出明确错误，不生成误导性结果。

解锁：

- P0-04 deterministic benchmark CI。
- P1 README benchmark 小表。

### P0-04：deterministic benchmarks 进入 CI

依赖：P0-03。

交付：

- GitHub Actions 跑：
  - `python -m pytest`
  - `python benchmarks/run_local.py --json`
- benchmark 阈值失败则 CI 失败。

验收：

- false-done block、freshness、cascade、TaskGraph、schema strictness 有固定阈值。
- CI badge 或 README 说明当前测试状态。

解锁：

- v0.5 release gate。
- 后续 benchmark 扩展。

### P0-05：维护 plan.md 单一事实源

依赖：P0-02。

交付：

- `plan.md` 保持当前真实状态。
- README 只引用 `plan.md` 作为未来路线和执行蓝本。
- 不再新增平行的计划、handoff、future 文档。

验收：

- 新会话只读 `plan.md` 就能知道下一步。

解锁：

- v0.5 主线。

---

## Phase 1：Credible Alpha

目标：外部用户打开 repo 后能快速理解价值、跑通 demo、相信 benchmark 边界。

版本出口：v0.5。

### P1-01：Refund 30 秒 demo

依赖：P0-02。

交付：

- `examples/refund_minimal.py`
- 展示完整闭环：
  1. claim `refund_completed`
  2. gate reject
  3. suggested action 指向缺失 evidence
  4. 补 `refund_api_response`
  5. assert accepted
  6. evidence expired 后 context blocked

验收：

- 无 API key。
- 一条命令运行。
- 输出能直接截图放 README。

解锁：

- P1-04 README 第一屏。
- P1-05 demo 截图。

### P1-02：Coding 30 秒 demo

依赖：P0-02。

交付：

- `examples/coding_minimal.py`
- 展示：
  - file evidence 支撑 diagnosis
  - 没有 fresh `test_log` 不能 claim done
  - fresh `test_log` 后 transition DONE

验收：

- 不依赖真实项目。
- 输出能证明 coding schema 和 refund schema 是同一内核。

解锁：

- P1-04 README 第一屏。
- P1-06 coding benchmark 方向。

### P1-03：Ticket / Compliance demo

依赖：P1-01 或 P1-02。

交付：

- `examples/ticket_minimal.py` 或 `examples/compliance_minimal.py`
- 新 schema 或 template 支持 `ticket_id` / `case_id`。

验收：

- 至少 3 个 TaskNode。
- 至少 1 次 blocked state transition。
- 至少 1 次 actionable rejection。

解锁：

- v0.5 更强的“enterprise workflow”叙事。

### P1-04：README 第一屏重写

依赖：P1-01、P1-02。

交付：

- 第一屏保留：
  - 一句话定位
  - 20 行以内 quickstart
  - rejected 输出
  - accepted 输出
- 架构图后置。

验收：

- 用户不看架构图也能理解：
  - EGM 拦什么
  - 缺什么证据
  - 怎么补
  - 为什么比普通 memory 更可信

解锁：

- v0.5 release。

### P1-05：demo 截图 / gif / 流程图

依赖：P1-01、P1-02。

交付：

- refund terminal screenshot
- coding terminal screenshot
- blocked -> fetch -> accepted 图

验收：

- README 能直接展示。
- 不依赖外部服务。

解锁：

- v0.5 release。

### P1-06：Benchmark philosophy 文档

依赖：P0-02。

交付：

- `docs/benchmark-philosophy.md`

内容：

- EGM 适合测什么。
- 哪些 benchmark 是 recall。
- 哪些 benchmark 是 grounding。
- 哪些 benchmark 是 process discipline。
- 哪些只是边界诊断。

验收：

- 解释为什么 tau-bench / tau2-bench 重要。
- 解释为什么 MemoryAgentBench 是 retrieval proxy。
- 解释为什么 LoCoMo / LongMemEval 不应作为主证明。

解锁：

- v0.5 release。
- Phase 2 benchmark 扩展。

### P1-07：Schema authoring guide 初版

依赖：P1-01、P1-02。

交付：

- `docs/schema-authoring.md`

内容：

- evidence types
- claim types
- source allowlist
- freshness TTL
- state transition gates
- entity extraction chain
- suggested action 写法

验收：

- 用户能照文档写一个 `ticket.yaml`。

解锁：

- P2 adapter 使用文档。
- v0.5 release。

---

## v0.5 出线标准

v0.5 名称：Credible Alpha。

必须全部满足：

1. 无 hardcoded credentials。
2. benchmark 叙事统一。
3. benchmark snapshot 可生成。
4. deterministic benchmark 进 CI。
5. refund demo 可一键运行。
6. coding demo 可一键运行。
7. README 第一屏完成重写。
8. 至少一张 demo 截图或终端输出进入 README。
9. `docs/benchmark-philosophy.md` 初版完成。
10. `docs/schema-authoring.md` 初版完成。
11. `python -m pytest` 通过。
12. PyPI release notes 写清这是 alpha，不是 full production。

如果只完成 tau-bench 扩展但没有 demo / README / docs，不发 v0.5。

---

## Phase 2：Adapter Beta

目标：EGM 不只在自己的 examples 里能用，还能接入主流 agent loop。

版本出口：v0.7。

### P2-01：LangChain adapter 最小版本

依赖：v0.5。

交付：

- `evidence_gated_memory.langchain`
- `EGMChatMessageHistory`
- `EGMRetriever`
- `EGMCallbackHandler`
- `evidence-gated-memory[langchain]`

验收：

- 能接 `RunnableWithMessageHistory`。
- retriever 返回 LangChain `Document`。
- callback 能把 tool output 记录成 evidence。
- 不要求用户理解 EGM 内部所有表结构。

解锁：

- P2-02 LangChain example。
- P2-05 adapter metadata contract。

### P2-02：LangChain refund agent example

依赖：P2-01。

交付：

- `examples/langchain_refund_agent.py`

验收：

- 展示 tool output -> evidence。
- 展示 final answer -> assert_fact。
- 展示 done transition -> gate。

解锁：

- v0.7 release。

### P2-03：LangGraph example

依赖：v0.5。

交付：

- `examples/langgraph_refund_agent.py`

验收：

- LangGraph 负责 orchestration。
- EGM 负责 evidence / facts / task state / context。
- 清楚展示在哪个 node 调用 EGM。

解锁：

- v0.7 release。

### P2-04：OpenAI Agents 或 generic agent loop example

依赖：v0.5。

交付：

- 一个不依赖 LangChain 的 agent loop example。

验收：

- tool result 后调用 `record_evidence`。
- answer 前调用 `assert_fact`。
- prompt 前调用 `build_context`。

解锁：

- v0.7 release。

### P2-05：Adapter metadata contract

依赖：P2-01。

交付：

- `docs/adapter-contract.md`

Retriever metadata 至少包含：

- `fact_id`
- `claim_type`
- `fact_kind`
- `task_id`
- `node_id`
- `evidence_refs`
- `freshness`
- `blocked`

Callback metadata 至少包含：

- `task_id`
- `tool_name`
- `evidence_id`
- `fact_id`
- `gate_result`
- `audit_id`

验收：

- 文档承诺哪些字段稳定。
- examples 使用这些字段。

解锁：

- v0.7 release。

### P2-06：扩大 tau-bench / tau2-bench A/B

依赖：P0-03。

交付：

- tau-bench retail 至少 30-task sample，目标完整 115-task。
- tau2 至少 30-task sample，或明确预算不足的边界。

验收：

- baseline vs EGM 数据。
- context compression。
- evidence coverage。
- rejection repair latency。
- 失败任务有 error class。

解锁：

- v0.7 release。
- v1.0 benchmark story。

---

## v0.7 出线标准

v0.7 名称：Adapter Beta。

必须全部满足：

1. v0.5 全部完成。
2. LangChain adapter 最小版本完成。
3. 至少一个 LangChain example。
4. 至少一个 LangGraph 或 generic agent loop example。
5. adapter metadata contract 初版完成。
6. tau-bench / tau2-bench 至少一个扩大样本结果。
7. README 有“如何接入现有 agent”的章节。
8. PyPI extras 正常安装。
9. tests 覆盖 adapter 的核心路径。

如果只做 adapter 没有 examples，不发 v0.7。

---

## Phase 3：Production Foundation

目标：从“能接入”推进到“长期 workspace、升级、审计、基本并发可控”。

版本出口：v0.8 / v0.9。

### P3-01：Versioned migration runner

依赖：v0.5。

交付：

- migration list
- `schema_meta.version`
- 自动迁移
- old schema fixture tests

验收：

- 旧 workspace 打开后能迁移。
- 迁移失败不 silent。
- 不再靠 `_ensure_column` 承担主要迁移职责。

解锁：

- P3-02 normalized storage。
- v1.0。

### P3-02：Normalized storage 设计与第一步落地

依赖：P3-01。

交付：

- 设计文档。
- 可选第一步表：
  - `fact_dependencies`
  - `fact_evidence_refs`
  - `fact_anchors`

验收：

- 不改 public API。
- cascade 查询可以不靠 JSON LIKE。
- 有 migration。

解锁：

- enterprise scale story。

### P3-03：CLI inspect 完整化

依赖：v0.5。

交付：

- `egm inspect`

输出：

- schema version
- evidence count
- active / blocked / invalidated facts
- tasks / nodes / edges
- L0/L1/L2/L3 counts
- offload records
- audit count

验收：

- 老 workspace 不崩。
- 缺表时明确显示 0 或 warning。

解锁：

- P3-04 audit export。

### P3-04：Audit export

依赖：P3-03。

交付：

- `egm export-audit --format json`
- `egm export-audit --format md`

验收：

- 支持按 `task_id` / `fact_id` / `evidence_id` 过滤。
- 能导出 rejection reason 和 suggested action。

解锁：

- enterprise adoption。

### P3-05：Production guide

依赖：P3-01、P3-03。

交付：

- `docs/production.md`

内容：

- SQLite workspace 边界
- 并发支持范围
- WAL / busy timeout 策略
- backup / migration
- audit export
- secrets handling
- schema review process

验收：

- 明确说哪些不是 v1.0 支持范围。

解锁：

- v1.0。

### P3-06：Workspace 并发策略

依赖：P3-05。

交付：

- WAL / busy_timeout 是否启用的明确决定。
- basic concurrent read/write tests。

验收：

- 文档和测试一致。
- 不夸大多 writer 能力。

解锁：

- v1.0。

### P3-07：Retention / archive 策略

依赖：P3-04。

交付：

- retention policy 文档。
- archive 格式。
- 默认不删除，除非用户显式执行。

验收：

- audit append-only 的原则不被破坏。

解锁：

- v1.0 optional。

---

## Phase 4：Professional Library

目标：达到 v1.0 专业 Python library 标准。

### P4-01：Typed package

依赖：v0.7。

交付：

- `py.typed`
- public API type hints 稳定
- mypy 或 pyright 基础检查

验收：

- 用户能在 typed project 里使用 EGM。

### P4-02：Packaging extras

依赖：P2-01。

交付：

- `evidence-gated-memory[langchain]`
- `evidence-gated-memory[dev]`
- 可选 `evidence-gated-memory[bench]`

验收：

- core install 保持轻。
- LangChain 用户只装需要的依赖。

### P4-03：Changelog 和 semver

依赖：v0.5。

交付：

- `CHANGELOG.md`
- release policy
- deprecation policy

验收：

- 每次 PyPI release 有明确变更。

### P4-04：Release criteria 文档

依赖：v0.7。

交付：

- `docs/release-criteria.md`

内容：

- v0.5 bar
- v0.7 bar
- v1.0 bar
- 什么情况下不能发版

验收：

- 发版前可逐项检查。

### P4-05：Observability metrics

依赖：P3-04。

交付：

- metrics API 或 export。

至少包含：

- facts accepted / rejected
- stale evidence rate
- false-done block rate
- evidence coverage
- context compression ratio
- rejection repair latency

验收：

- demo 或 inspect 能展示这些指标。

---

## v1.0 出线标准

v1.0 名称：Professional Python Library。

必须全部满足：

1. v0.5 全部完成。
2. v0.7 全部完成。
3. versioned migration runner 完成。
4. production guide 完成。
5. CLI inspect 完整可用。
6. audit export 可用。
7. strict schema 稳定。
8. public API 文档稳定。
9. typed package / `py.typed` 完成。
10. GitHub Actions 稳定跑 tests + deterministic benchmarks。
11. 至少 3 个 polished demos。
12. 至少 2 个生态接入示例。
13. benchmark snapshot 可复现。
14. README 和实际代码一致。
15. 没有 hardcoded secrets。
16. PyPI packaging extras 可用。
17. CHANGELOG 和 semver 已建立。
18. `docs/release-criteria.md` 已建立。

如果 migration、audit export、production guide 没有完成，不发 v1.0。

---

## 依赖图

核心依赖顺序：

```text
P0-01 credentials cleanup
  -> P0-02 benchmark truth
  -> P0-03 benchmark snapshot
  -> P0-04 CI benchmark gate
  -> v0.5 foundation

P1-01 refund demo
  -> P1-04 README first screen
  -> v0.5

P1-02 coding demo
  -> P1-04 README first screen
  -> v0.5

v0.5
  -> P2-01 LangChain adapter
  -> P2-02 LangChain example
  -> v0.7

v0.5
  -> P3-01 migration runner
  -> P3-03 CLI inspect
  -> P3-04 audit export
  -> v1.0

v0.7
  -> P4 typed package / extras / release policy
  -> v1.0
```

---

## 做事规则

### 每个 slice 都要满足

1. 不破坏 gate invariants。
2. 不绕过 audit。
3. 不扩大 public API 后再补文档。
4. 不把 benchmark smoke 写成正式结果。
5. 不把 LLM 输出当成高可信 evidence。
6. 不为了 demo 改低 gate 严格性。
7. 每次改 README，必须确认代码真的支持。

### 什么时候应该停下来让人审

这些改动需要二次审议：

- state transition gate 规则变化
- `commit_fact` / gate 写入路径变化
- derived fact cascade 语义变化
- schema migration 机制变化
- public API breaking change
- v0.5 / v0.7 / v1.0 发版前

### 暂时不要做，但未来可以做

这些不进 v0.5 / v0.7 主线，不代表永远不做。原因是它们会显著扩大项目边界，必须等 core library 可信、可接入、可迁移之后再进入。

| 方向 | 现在为什么不做 | 未来什么时候做 | 未来形态 |
|---|---|---|---|
| Hosted service | 会把项目从 Python library 变成平台，运维、认证、计费、隔离都会压过核心 memory 问题 | v1.0 后，如果有真实团队要求多语言 / 多服务共享 EGM | 独立 `egm-server`，提供 HTTP API，但 core library 仍然是主产品 |
| UI dashboard | UI 会消耗大量设计和前端成本；现在最缺的是 demo、benchmark、adapter，而不是控制台 | audit export / inspect 稳定后 | 只做 audit viewer / task graph viewer，不做全功能 agent platform |
| Postgres backend | 现在 SQLite 更适合嵌入式库；Postgres 会引入部署复杂度和 migration 成本 | normalized storage 和 migration runner 稳定后 | `SqliteStore` 之外新增 `PostgresStore`，保持同一 storage interface |
| Vector database plugin | EGM 的核心不是向量搜索，而是 evidence gate；过早加 vector 会稀释定位 | LangChain retriever contract 稳定后 | 插件式 retriever backend，可选 FAISS / Chroma / pgvector，不替代 gate |
| Automatic LLM distillation | L0->L1 自动提炼如果没 source span / confidence / approval，会污染记忆层 | manual L0/L1/L2/L3 稳定后，且有 pending-review 机制 | `candidate_atom` 队列，LLM 只提候选，gate / human 决定是否 promote |
| Complex permission system | 权限系统会把 library 变成企业平台，当前还没有足够使用反馈 | hosted service 或 Postgres multi-tenant 需求出现后 | resource-level permission，不进入 core v1.0 |
| Full agent framework | EGM 不应该和 LangGraph / LangChain / OpenAI Agents 抢编排位置 | 不建议做 | 只做 adapter，不做自己的通用 agent framework |

---

## Later Roadmap：v1.1 以后可以扩展什么

v1.0 之前的重点是把 EGM 做成成熟 Python library。v1.0 之后，才考虑更大的产品形态。

### L1：Postgres backend

前置条件：

- versioned migration runner 已稳定
- storage interface 已抽象清楚
- SQLite schema 已经正规化，至少不再依赖关键路径 JSON LIKE
- 有用户明确需要共享 DB 或长生命周期 workspace

交付形态：

- `evidence_gated_memory.storage.postgres.PostgresStore`
- 同一 public API，不让用户换数据库就改业务代码
- Postgres migration 独立于 SQLite migration
- 最小支持 facts、evidence、tasks、audit、memory pyramid

不做：

- 不把 Postgres 变成默认后端
- 不在 v1.0 前引入

### L2：Vector / hybrid retrieval plugin

前置条件：

- `EGMRetriever` metadata contract 已稳定
- benchmark 已证明现有 FTS 的边界
- 用户需要语义召回，而不是仅 hard-anchor 召回

交付形态：

- 可选 extra：`evidence-gated-memory[vector]`
- 插件式 backend：
  - FAISS
  - Chroma
  - pgvector
- hybrid retrieval：
  - hard anchor / FTS 先召回
  - vector 只做补充
  - gate 和 freshness 仍然是最终准入层

不做：

- 不让 vector result 直接成为 fact
- 不让 embedding score 替代 evidence quality

### L3：Audit / TaskGraph UI

前置条件：

- `egm inspect` 和 `egm export-audit` 稳定
- TaskGraph / audit JSON export 格式稳定
- README demo 已经足够清楚

交付形态：

- 静态 viewer 优先，而不是完整后台系统
- 功能只聚焦：
  - task graph
  - evidence chain
  - gate rejection history
  - freshness status
  - audit replay

不做：

- 不做 agent builder
- 不做 prompt playground
- 不做完整 SaaS 控制台

### L4：egm-server

前置条件：

- core library v1.0 稳定
- Postgres backend 可用
- audit export / inspect 稳定
- 有真实多进程 / 多服务共享 EGM 的需求

交付形态：

- 独立 package 或子项目：`egm-server`
- HTTP API：
  - record evidence
  - assert fact
  - transition node
  - build context
  - inspect / audit export
- 仍然不做 agent orchestration

不做：

- 不在 core library 里塞 web server
- 不把 hosted service 作为默认使用方式

### L5：Automatic LLM distillation

前置条件：

- manual promotion 流程稳定
- source span / confidence / provenance model 明确
- 有 candidate review 队列
- 有 benchmark 能测 memory pollution

交付形态：

- LLM 只生成 candidate atom
- candidate 必须包含：
  - source message ids
  - source spans
  - confidence
  - extraction rationale
  - conflict flags
- promote 必须经过：
  - deterministic checks
  - optional human review
  - audit log

不做：

- 不允许 LLM 自动直接写 L1 atom
- 不允许无 source span 的自动长期记忆进入 prompt

### L6：Enterprise governance

前置条件：

- egm-server 或 Postgres multi-tenant 需求出现
- audit / retention / export 已稳定

交付形态：

- workspace-level policy
- schema review workflow
- retention policy
- PII redaction hooks
- role-based audit visibility

不做：

- 不在 core alpha 阶段引入复杂权限系统

---

## 下一次打开项目时，从这里开始

第一步：跑基础验证。

```bash
python -m pytest
python benchmarks/run_local.py --json
```

第二步：做 Phase 0。

```text
P0-01 -> P0-02 -> P0-03 -> P0-04 -> P0-05
```

第三步：进入 v0.5。

```text
P1-01 refund demo
P1-02 coding demo
P1-04 README first screen
P1-06 benchmark philosophy
P1-07 schema authoring guide
```

只要没有完成 v0.5，不要急着扩大到 UI、服务化、Postgres、向量插件。

---

## 最短总结

EGM 下一步不是“加更多功能”。  
下一步是把现在已经有的核心能力变成：

- 能被看懂
- 能被验证
- 能被接入
- 能被升级
- 能被审计

这就是从 alpha 项目走向成熟 Python library 的路线。
