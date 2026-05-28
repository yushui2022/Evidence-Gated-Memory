# EGM Execution Plan

Date: 2026-05-28

## 这份 plan.md 的作用

这是 EGM 后续开发的唯一主蓝本。它已经吸收并取代早期的状态交接、Codex 注意事项和未来路线文档。

以后判断“下一步做什么”，只看这个文件。  
以后判断“能不能发 v0.5 / v0.7 / v0.8 / v0.9 / v1.0”，也看这个文件。

---

## 产品定位与边界

EGM 的最高定位：

> Evidence-Gated Memory 是一个面向 hard-anchor 企业 Agent 的证据门控图记忆 Python library。

它要解决的不是“让 Agent 记住更多聊天内容”，而是让 Agent 在订单、工单、退款、合规、财务、代码修复这类高风险流程里，只能把有证据、未过期、可追溯、可审计的结论提升为事实，并把当前任务状态维护成可恢复的图结构。

核心产品形态：

- 首要形态：可 `pip install` 的 Python library。
- 核心用户：正在写业务 Agent / workflow Agent 的开发者。
- 核心场景：有明确 anchor 的企业任务，例如 `order_id`、`ticket_id`、`case_id`、`pull_request_id`、`invoice_id`。
- 核心能力：refs 原始证据、evidence gate、freshness、derived fact cascade、DAG-style TaskGraph、Mermaid projection、audit log、context builder。
- 成熟方向：让 EGM 更容易接入现有 agent loop，而不是自己变成通用 Agent 框架。

统一治理范式：

```text
短期事实：claim candidate -> evidence gate -> fact
任务状态：transition candidate -> state gate -> task state
长期记忆：atom candidate -> memory gate -> L1 atom
```

这意味着 LLM 可以提候选，但不能直接写事实；LLM 可以整理记忆，但不能直接晋升记忆。EGM 的差异不是“自动记忆”，而是“只能通过 gate 沉淀记忆”。

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
9. 长期记忆自动化时，LLM 只能产出 `CandidateAtom`，必须经 candidate gate 才能进入 L1。
10. 如果使用 LangChain / LangGraph / OpenAI Agents，adapter 只负责把这些步骤接到对应 agent loop 里，不改变 EGM 的证据规则。

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
- generic agent loop / LangChain / LangGraph / OpenAI Agents 接入还不够成熟
- production guide、audit export、observability 还不完整
- 企业级并发、retention、normalized storage 还只是设计债
- 真实外部开发者无辅助接入验证还没有做
- TaskGraph 已经是 directed graph，但还没有强制多节点无环；对外只能说 DAG-style，不能说 enforced DAG

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
11. Direct automatic L0 -> L1 promotion is forbidden. LLM may only produce candidate atoms with source spans, confidence, rationale, and conflict flags. A candidate gate must decide promote / pending review / reject, and every decision must write audit.
12. 新 FTS 查询路径必须经过安全 sanitize，并保留 fallback。
13. schema migration 必须显式处理，不能继续只靠 `CREATE TABLE IF NOT EXISTS`。
14. TaskGraph / fact lineage 可以按 DAG 设计，但在代码强制 cycle rejection 之前，对外只能称为 DAG-style，不得称为 enforced DAG。

---

## 总路线

项目接下来分成五个阶段：

| 阶段 | 名称 | 目标 | 版本出口 |
|---|---|---|---|
| Phase 0 | Truth & Safety | 把当前状态、benchmark、凭据、README 说法收干净 | v0.4.x patch |
| Phase 1 | Credible Alpha | 让外部用户能看懂、跑通、相信 | v0.5 |
| Phase 2 | Adapter Beta | 让别人能接到自己的 agent loop | v0.7 |
| Phase 3A | Production Hygiene | 让长期 workspace、升级、审计、基础运维可控 | v0.8 |
| Phase 3B | Storage & Memory Promotion | 正规化存储、长期记忆 candidate gate、DAG invariant 加固 | v0.9 |
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

- P0-06 benchmark decision protocol。
- P1 README 第一屏重写。

### P0-06：Benchmark decision protocol

依赖：P0-02。

交付：

- `docs/benchmark-decision-protocol.md`
- 明确两类指标：
  - EGM 原生指标：unsupported claim block、false-done block、freshness、cascade、actionable rejection、audit completeness。
  - downstream agent 指标：tau-bench / tau2-bench pass rate、context compression、evidence coverage、rejection repair latency。
- 明确 sample size 口径：
  - 3-task / 8-task 只能叫 smoke。
  - 30-task 可以叫 small sample。
  - 完整 tau-bench / tau2-bench 才能接近正式 A/B。
- 明确预算不足时如何写 limitation。

验收：

- README 不把 EGM 原生指标和下游 agent 指标混写。
- tau-bench / tau2-bench 小样本结果必须附带 sample size 和 limitation。
- 如果 pass rate 不显著，但 false-done / unsupported-claim 明显下降，宣传口径必须写成 process discipline / trust improvement，而不是 task success improvement。

解锁：

- P0-03 benchmark snapshot。
- P1-06 benchmark philosophy。

### P0-03：benchmark snapshot 生成器

依赖：P0-06。

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

依赖：P0-06。

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
- README 必须把 EGM 的核心结构明确表述为“三张有向依赖图共用一套 gate 纪律”（task graph / fact lineage / long-term memory provenance），并保留不变量 #14 的措辞边界：当前只能写 DAG-style，不得写 enforced DAG。

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

依赖：P0-06。

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

### P1-08：Unaided adoption test

依赖：P1-01、P1-02、P1-04。

目标：

验证一个非作者开发者能不能独立理解并接入 EGM，而不是只听完介绍后礼貌性认可。

交付：

- 找 3 个 hard-anchor agent 开发者试用。
- 至少 1 个开发者在没有作者实时指导的情况下，把 EGM 接进自己的 agent 或一个非官方 demo 任务。
- 记录完整 friction log：
  - 哪一步看不懂。
  - 哪个 API 不知道该放在哪里。
  - 是否误解 TaskGraph / schema / gate。
  - 是否觉得“我只想要 callback，不想接受这整套心智模型”。
- 根据反馈反向修改 README / quickstart / examples / API。

验收：

- 至少 1 个外部开发者能在 60-90 分钟内跑通非官方场景。
- 如果没人能独立跑通，v0.5 不能宣称 “easy to adopt”。
- 如果 3 个开发者都不愿意接入，暂停 v0.7 adapter，先重审产品形态。

解锁：

- v0.5 release。
- Phase 2 adapter 优先级。

### P1-09：DAG invariant hardening design

依赖：P1-01、P1-02。

目标：

把当前 DAG-style TaskGraph / fact lineage 的边界讲清楚，并为后续 enforced DAG 做设计。v0.5 可以先完成设计和文档；代码层面的 cycle rejection 可以在 v0.7 / v0.9 分步落地。

交付：

- `docs/dag-invariants.md`
- 明确三类有向依赖：
  - TaskGraph：TaskNode -> TaskNode。
  - Fact lineage：Evidence -> observed fact -> derived fact。
  - Long-term memory provenance：L0 -> candidate atom -> L1 -> L2 -> L3。
- 明确当前状态：
  - 已禁止 self-loop 和 cross-task edge。
  - 尚未强制多节点 cycle rejection。
  - 对外文案只能写 DAG-style，不写 enforced DAG。

验收：

- README / docs 不夸大当前 DAG 约束。
- 后续实现项清楚列出：
  - A -> B -> C 后禁止 C -> A。
  - parent_id 禁止祖先回指。
  - derived fact depends_on 禁止自依赖和环。

解锁：

- P3-09 TaskGraph cycle rejection。
- P3 normalized fact dependency storage。

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
11. `docs/benchmark-decision-protocol.md` 初版完成。
12. `docs/dag-invariants.md` 初版完成。
13. Unaided adoption test 至少完成 3 个试用邀请和 1 个真实接入尝试；如果没有跑通，README 不得宣称 easy adoption。
14. `python -m pytest` 通过。
15. PyPI release notes 写清这是 alpha，不是 full production。

如果只完成 tau-bench 扩展但没有 demo / README / docs，不发 v0.5。

---

## Phase 2：Adapter Beta

目标：EGM 不只在自己的 examples 里能用，还能接入真实 agent loop。先证明裸 loop 接入范式，再包装 LangChain / LangGraph / OpenAI Agents；不要把任何单一框架当成地基。

版本出口：v0.7。

### P2-01：Generic agent loop integration guide

依赖：v0.5。

交付：

- `docs/generic-agent-loop.md`
- 一个不依赖 LangChain / LangGraph 的接入模板。
- 明确四个稳定调用点：
  - tool result 后调用 `record_evidence()`
  - answer / business conclusion 前调用 `assert_fact()`
  - 状态变更前调用 `transition_node()`
  - prompt 前调用 `build_context()`

验收：

- 用户不看任何框架 adapter，也知道 EGM 应该插在 agent loop 的哪里。
- guide 不要求用户先理解 SQLite 表结构。

解锁：

- P2-02 generic refund agent example。
- P2-03 adapter metadata contract。

### P2-02：Generic refund agent example

依赖：P2-01。

交付：

- `examples/generic_refund_agent.py`

验收：

- 展示 tool output -> evidence。
- 展示 final answer -> assert_fact。
- 展示 done transition -> gate。
- 展示 build_context 如何进入下一轮 prompt。

解锁：

- v0.7 release。

### P2-03：Adapter metadata contract

依赖：P2-01。

交付：

- `docs/adapter-contract.md`

Retriever / context metadata 至少包含：

- `fact_id`
- `claim_type`
- `fact_kind`
- `task_id`
- `node_id`
- `evidence_refs`
- `freshness`
- `blocked`

Callback / event metadata 至少包含：

- `task_id`
- `tool_name`
- `evidence_id`
- `fact_id`
- `gate_result`
- `audit_id`

验收：

- 文档承诺哪些字段稳定。
- generic example 使用这些字段。

解锁：

- P2-04 LangChain adapter。
- v0.7 release。

### P2-04：LangChain adapter 最小版本

依赖：P2-01、P2-03。

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

- P2-05 ecosystem examples。
- v0.7 release。

### P2-05：LangChain / LangGraph / OpenAI Agents examples

依赖：P2-01、P2-03、P2-04。

交付：

- `examples/langchain_refund_agent.py`
- `examples/langgraph_refund_agent.py` 或 `examples/openai_agents_refund_agent.py`

验收：

- LangChain example 展示 adapter 的最小可用路径。
- LangGraph / OpenAI Agents example 展示 EGM 只负责 evidence / facts / task state / context，不抢 orchestration。
- 如果某个框架 API 变化太大，保留 generic loop 为主路径，不阻塞 v0.7。

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

### P2-07：Long-term candidate gate design

依赖：P2-01。

目标：

把长期记忆从“纯手动 promotion”推进到“LLM 产候选，gate 决定晋升”的设计阶段，但 v0.7 不直接承诺完整自动化实现。

交付：

- `docs/long-term-candidate-gate.md`
- `CandidateAtom` 草案字段：
  - `id`
  - `kind: persona | episodic | instruction`
  - `text`
  - `source_message_ids`
  - `source_spans`
  - `confidence`
  - `extraction_rationale`
  - `conflict_flags`
  - `supersedes_atom_ids`
  - `metadata`
  - `created_at`
- `CandidateGateResult` 草案字段：
  - `accepted`
  - `violations`
  - `confidence_policy`
  - `conflict_policy`
  - `suggested_action`
  - `audit_id`

验收：

- 明确禁止 `LLM summary -> MemoryAtom` 直写路径。
- 明确 `source_spans` 至少包含 `message_id`、`start_char`、`end_char`、`quoted_text_hash`。
- 明确三种结果：
  - 高 confidence + 有 source span + 无冲突：auto promote。
  - 中 confidence 或有潜在冲突：pending review。
  - 低 confidence / 无 source span / source 不存在：reject。
- L2 / L3 自动化继续后置，默认需要 review。

解锁：

- P3-08 L1 candidate gate implementation。

---

## v0.7 出线标准

v0.7 名称：Adapter Beta。

必须全部满足：

1. v0.5 全部完成。
2. generic agent loop integration guide 完成。
3. generic refund agent example 完成。
4. adapter metadata contract 初版完成。
5. LangChain adapter 最小版本完成。
6. 至少一个 LangChain example。
7. 至少一个 LangGraph 或 OpenAI Agents example；如果框架 API 风险太大，必须在 release notes 里解释为什么保留 generic loop 为主路径。
8. tau-bench / tau2-bench 至少一个扩大样本结果。
9. `docs/long-term-candidate-gate.md` 初版完成。
10. README 有“如何接入现有 agent”的章节。
11. PyPI extras 正常安装。
12. tests 覆盖 adapter 的核心路径。

如果只做 adapter 没有 examples，不发 v0.7。

---

## Phase 3A：Production Hygiene

目标：从“能接入”推进到“长期 workspace、升级、审计、基础运维可控”。

版本出口：v0.8。

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
- v0.8。

### P3-02：Normalized storage 设计

依赖：P3-01。

交付：

- 设计文档。
- 候选第一步表：
  - `fact_dependencies`
  - `fact_evidence_refs`
  - `fact_anchors`
- migration plan。

验收：

- 不改 public API。
- 明确哪些查询今天仍靠 JSON LIKE。
- 明确哪些表进入 v0.9 第一批实现。

解锁：

- enterprise scale story。
- P3-10 normalized storage first implementation。

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

- v0.8。

### P3-06：Workspace 并发策略

依赖：P3-05。

交付：

- WAL / busy_timeout 是否启用的明确决定。
- basic concurrent read/write tests。

验收：

- 文档和测试一致。
- 不夸大多 writer 能力。

解锁：

- v0.8。

### P3-07：Retention / archive 策略

依赖：P3-04。

交付：

- retention policy 文档。
- archive 格式。
- 默认不删除，除非用户显式执行。

验收：

- audit append-only 的原则不被破坏。

解锁：

- v0.8 optional。

---

## v0.8 出线标准

v0.8 名称：Production Hygiene。

必须全部满足：

1. v0.7 全部完成。
2. versioned migration runner 完成。
3. normalized storage 设计完成。
4. CLI inspect 完整可用。
5. audit export 可用。
6. production guide 完成。
7. workspace 并发边界有文档和基础测试。
8. retention / archive 策略至少有文档，默认不删除。
9. release notes 明确 v0.8 仍不是 hosted service，也不是多 writer 企业平台。

如果 migration runner、inspect、audit export、production guide 没有完成，不发 v0.8。

---

## Phase 3B：Storage & Memory Promotion

目标：把底层依赖查询、长期记忆晋升和 DAG invariant 从设计推进到可执行实现。

版本出口：v0.9。

### P3-08：L1 candidate gate implementation

依赖：P2-07。

交付：

- `CandidateAtom` model / storage。
- `CandidateGateResult` model。
- L0 -> CandidateAtom 的接口，LLM provider 可插拔。
- `promote_candidate_atom()` 或等价 API。
- audit events：
  - `memory_candidate_created`
  - `memory_candidate_promoted`
  - `memory_candidate_rejected`
  - `memory_candidate_pending_review`

验收：

- 无 source span 的 candidate 必须 reject。
- source message 不存在必须 reject。
- 低 confidence 必须 reject 或 pending，不得进入 prompt。
- 有冲突的 candidate 必须 pending review 或显式 supersede。
- auto promote 也必须写 audit。
- L2 / L3 不自动 promote，除非后续单独设计。

解锁：

- 长期记忆真实自动化使用。
- v0.9。

### P3-09：DAG invariant enforcement

依赖：P1-09、P3-01。

交付：

- TaskGraph edge cycle detection。
- TaskNode `parent_id` cycle detection。
- derived fact depends_on 自依赖 / 环检测设计；如果实现依赖 normalized storage，则明确分阶段落地。
- 针对旧 workspace 中非法图的 inspect warning。

验收：

- A -> B -> C 后，新增 C -> A 被拒绝。
- self-loop 继续被拒绝。
- parent_id 不能指向自己或祖先。
- README 可以在完成后把 TaskGraph 从 DAG-style 改成 enforced DAG；完成前不能改。

解锁：

- 更强 DAG 叙事。
- v0.9。

### P3-10：Normalized storage first implementation

依赖：P3-02、P3-01。

交付：

- 至少落地一个关键 junction table：
  - `fact_dependencies` 优先。
  - 其次是 `fact_evidence_refs` 或 `fact_anchors`。
- 对应 migration。
- 对应 DAO / tests。

验收：

- 不改 public API。
- cascade 查询至少一条关键路径不再依赖 JSON LIKE。
- 旧 workspace 可迁移。

解锁：

- fact lineage DAG enforcement。
- v0.9。

---

## v0.9 出线标准

v0.9 名称：Storage & Memory Promotion。

必须全部满足：

1. v0.8 全部完成。
2. normalized storage 至少完成关键依赖表设计和一项落地。
3. L1 candidate gate implementation 完成。
4. TaskGraph cycle rejection 完成。
5. derived fact depends_on 环检测至少有明确实现路径；如果未完成，不能宣传 full enforced lineage DAG。
6. benchmark / tests 能测 memory pollution 或 candidate rejection。
7. docs 写清 LLM 可以提候选，但不能直接晋升记忆。

如果 L1 candidate gate 没有完成，不发 v0.9。

---

## Phase 4：Professional Library

目标：达到 v1.0 专业 Python library 标准。

### P4-01：Typed package

依赖：v0.9。

交付：

- `py.typed`
- public API type hints 稳定
- mypy 或 pyright 基础检查

验收：

- 用户能在 typed project 里使用 EGM。

### P4-02：Packaging extras

依赖：P2-04。

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
- v0.8 bar
- v0.9 bar
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
3. v0.8 全部完成。
4. v0.9 全部完成。
5. strict schema 稳定。
6. public API 文档稳定。
7. typed package / `py.typed` 完成。
8. GitHub Actions 稳定跑 tests + deterministic benchmarks。
9. 至少 3 个 polished demos。
10. 至少 2 个生态接入示例，其中 generic loop 必须是主路径之一。
11. benchmark snapshot 可复现。
12. README 和实际代码一致。
13. 没有 hardcoded secrets。
14. PyPI packaging extras 可用。
15. CHANGELOG 和 semver 已建立。
16. `docs/release-criteria.md` 已建立。
17. 真实用户验证结论已经反映到 README / quickstart / adapter 优先级。
18. 如果仍然只实现 DAG-style 而非 full enforced lineage DAG，文档必须清楚写出边界。

如果 migration、audit export、production guide 没有完成，不发 v1.0。

---

## 依赖图

核心依赖顺序：

```text
P0-01 credentials cleanup
  -> P0-02 benchmark truth
  -> P0-06 benchmark decision protocol
  -> P0-03 benchmark snapshot
  -> P0-04 CI benchmark gate
  -> v0.5 foundation

P1-01 refund demo
  -> P1-04 README first screen
  -> v0.5

P1-02 coding demo
  -> P1-04 README first screen
  -> v0.5

P1-04 README first screen
  -> P1-08 unaided adoption test
  -> v0.5

P1-09 DAG invariant design
  -> P3-09 DAG invariant enforcement
  -> v0.9

v0.5
  -> P2-01 generic agent loop
  -> P2-03 adapter metadata contract
  -> P2-04 LangChain adapter
  -> v0.7

P2-07 long-term candidate gate design
  -> P3-08 L1 candidate gate implementation
  -> v0.9

v0.5
  -> P3-01 migration runner
  -> P3-03 CLI inspect
  -> P3-04 audit export
  -> v0.8

v0.8
  -> P3-08 L1 candidate gate
  -> P3-09 DAG enforcement
  -> P3-10 normalized storage first implementation
  -> v0.9

v0.9
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
8. 不把 DAG-style 文档写成 enforced DAG，除非代码已经强制 cycle rejection。
9. 不让 LLM 直接 promote fact 或 memory atom；必须先进入 candidate / gate / audit 路径。

### 什么时候应该停下来让人审

这些改动需要二次审议：

- state transition gate 规则变化
- `commit_fact` / gate 写入路径变化
- derived fact cascade 语义变化
- schema migration 机制变化
- public API breaking change
- v0.5 / v0.7 / v0.8 / v0.9 / v1.0 发版前

### Reality Check：什么时候承认假设可能错

这些信号不是普通 TODO，而是路线需要暂停、重审、甚至 pivot 的信号。

v0.5 发布后 60 天内，如果出现以下情况：

- 3 个真实 hard-anchor agent 开发者都无法或不愿独立接入。
- 重写 README / quickstart 后仍然没有改善。
- 外部反馈集中在“概念太重”“我只想要 callback”“schema 成本太高”“TaskGraph 心智负担太大”。

动作：

- 暂停 v0.7 adapter 开发。
- 重审产品形态：
  - 保持完整 EGM library。
  - 拆出轻量 EGM callback / middleware。
  - 把 TaskGraph 从默认路径降级为高级能力。
  - 聚焦某一个垂直场景，例如 refund / compliance / coding verification。

v0.7 发布后，如果出现以下情况：

- generic loop 有人能用，但 LangChain adapter 无人使用。
- 用户只想接 `record_evidence()` / `assert_fact()` / `build_context()`，不想引入框架 adapter。

动作：

- 降低 LangChain / LangGraph 优先级。
- 把 generic loop 保持为 README 主路径。

tau-bench / tau2-bench 扩大样本后，如果出现以下情况：

- pass rate 没有显著提升。
- 但 false-done / unsupported-claim / evidence coverage 明显改善。

动作：

- 不宣传 task success improvement。
- 改宣传 process discipline / trust improvement。

如果连 EGM 原生指标都没有优势：

- 停止扩大 adapter。
- 重审 gate schema、actionable rejection、freshness、cascade 这些核心假设。

### 暂时不要做，但未来可以做

这些不进 v0.5 / v0.7 主线，不代表永远不做。原因是它们会显著扩大项目边界，必须等 core library 可信、可接入、可迁移之后再进入。

| 方向 | 现在为什么不做 | 未来什么时候做 | 未来形态 |
|---|---|---|---|
| Hosted service | 会把项目从 Python library 变成平台，运维、认证、计费、隔离都会压过核心 memory 问题 | v1.0 后，如果有真实团队要求多语言 / 多服务共享 EGM | 独立 `egm-server`，提供 HTTP API，但 core library 仍然是主产品 |
| UI dashboard | UI 会消耗大量设计和前端成本；现在最缺的是 demo、benchmark、adapter，而不是控制台 | audit export / inspect 稳定后 | 只做 audit viewer / task graph viewer，不做全功能 agent platform |
| Postgres backend | 现在 SQLite 更适合嵌入式库；Postgres 会引入部署复杂度和 migration 成本 | normalized storage 和 migration runner 稳定后 | `SqliteStore` 之外新增 `PostgresStore`，保持同一 storage interface |
| Vector database plugin | EGM 的核心不是向量搜索，而是 evidence gate；过早加 vector 会稀释定位 | LangChain retriever contract 稳定后 | 插件式 retriever backend，可选 FAISS / Chroma / pgvector，不替代 gate |
| Full automatic L2/L3 distillation | L3 persona 会长期影响 prompt，自动化过早会污染长期行为 | L1 candidate gate 稳定后，且有 pending-review 机制 | LLM 只提 L2/L3 候选，gate / human 决定是否 promote |
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

### L5：Advanced L2/L3 candidate distillation

前置条件：

- L1 candidate gate 已稳定
- source span / confidence / provenance model 已被真实使用验证
- 有 candidate review 队列
- 有 benchmark 能测 memory pollution
- 有用户明确需要自动生成 scenario / persona，而不是只需要 L1 atom

交付形态：

- LLM 只生成 L2 / L3 candidate，不直接写 scenario / persona
- candidate 必须包含：
  - source message ids
  - source spans
  - confidence
  - extraction rationale
  - conflict flags
- promote 必须经过：
  - deterministic checks
  - human review by default
  - audit log

不做：

- 不允许 LLM 自动直接写 L2 scenario / L3 persona
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
P0-01 -> P0-02 -> P0-06 -> P0-03 -> P0-04 -> P0-05
```

第三步：进入 v0.5。

```text
P1-01 refund demo
P1-02 coding demo
P1-04 README first screen
P1-06 benchmark philosophy
P1-07 schema authoring guide
P1-08 unaided adoption test
P1-09 DAG invariant design
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
