# Memoria 小范围改进开发需求

日期：2026-09-23　状态：待开发　范围：6 项局部改进

关联：[改进清单](../memoria-small-improvements.md) · [验收报告与测试用例](../memoria-small-improvements-acceptance.md)

## 1. 目标与边界

提升检索正确性、输入契约一致性、故障可观测性及发布可复现性。基线为本地 `689f3f9badf0ae1eba3652ab91a8a329dc08701b`（v0.5.2）；实施前合并最新主分支并核对依赖 PR。

不新增第三方依赖，不改数据库 schema，不改检索权重，不扩大到权限空间、SSE 重构、取消执行、语义去重或新 benchmark。复用现有 Rust 测试框架和 CI。以下是需求，不表示代码已实现。

## 2. 功能需求

### R1：全文独有候选不得获得虚假的向量分数

- 问题：全文返回的 `retrieval_score` 保存全文分数；hybrid 合并后又读取该字段作为向量分数，全文独有候选被重复加分。
- 位置：`memoria/crates/memoria-storage/src/store.rs::search_hybrid_from_scored_scoped`。
- 最小实现：保留 `ft_map`，将全文独有候选的向量分量明确置零；共同命中候选保留原向量分数，关键词分量仍按原公式计算。
- 兼容要求：候选 ID 去重、过滤条件、Top-K、置信与时间衰减、反馈调节、排序和 explain 字段语义保持一致。
- 验收：A01–A02。固定输入必须检出旧代码的错误，不能只断言“接口成功”。

### R2：各写入入口一致拒绝非法 memory_type

- 问题：embedded MCP 把非法类型静默转换为 `semantic`，REST 已拒绝非法类型。
- 位置：MCP `tools.rs`、`remote.rs`；复用 `memoria-core::MemoryType` 解析与合法值集合，REST 作为兼容参照。
- 最小实现：字段缺省时使用 `semantic`；显式字段仅接受 `semantic`、`working`、`episodic`、`profile`、`tool_result`、`procedural`。空串、空白、未知值、非字符串及显式 null 均拒绝。不增加自动纠错或大小写转换。
- 校验必须早于 embedding、存储写入及 remote HTTP 转发；错误描述指出字段及合法值，不暴露内部配置。
- MCP 参数业务校验失败使用工具结果 `isError: true`，不得返回普通成功文本；REST 返回现有 4xx 校验契约。外层 JSON-RPC 信封错误仍按协议处理。
- 依赖：优先复用 [PR #258](https://github.com/matrixorigin/memoria/pull/258) 的错误结果机制。若尚未合并，先处理依赖，不另建第二套错误体系。
- 验收：A03–A06。零副作用须由调用计数和存储状态证明，不能仅检查返回文本。

### R3：hybrid 全文降级有结构化日志

- 问题：全文分支失败被 `unwrap_or_default()` 隐藏，与正常空结果无法区分。
- 最小实现：原位置区分 `Ok(empty)` 与 `Err`；失败时继续现有向量路径，并记录 warning：`operation=hybrid_search`、`failed_leg=fulltext`、`fallback=vector`、稳定的 `error_kind`，可附已有请求关联 ID。
- 不直接记录原始 SQL 错误字符串，避免夹带正文、查询文本、连接串或凭据；不增加日志服务、指标 schema 或重试。
- 兼容要求：本次不改变向量失败时的传播策略，也不把纯全文入口改成 LIKE。
- 验收：A07–A09。

### R4：PR 与发布测试使用固定 MatrixOne 镜像

- 修改 `.github/workflows/test.yml` 与 `.github/workflows/test-gate.yml`，使用同一已验证镜像 digest，禁止两处各自漂移。
- 从受支持且可运行的镜像选择基线；benchmark 的历史 digest 只是候选，不能未验证就认定兼容。
- CI 记录实际镜像 digest、Rust 版本、被测 SHA。保持现有数据库回归步骤。
- 验收：A10。镜像升级通过显式 PR 完成，本轮不新增 nightly 矩阵。

### R5：手动发布也验证实际发布的提交

- 范围为 Rust 二进制发布链及其共享 Test Gate，不扩大到 npm／Docker 发布策略重构。
- `workflow_dispatch` 不再绕过 gate；tag push 和手动选择 tag 均解析为确定的 commit SHA，测试与构建使用同一 SHA。
- 复用 Test Gate 时增加必要的 ref 输入并保留合理默认，不能破坏 Docker 发布等既有调用方。
- gate 为 failure、cancelled 或 skipped 时不得进入构建／发布；tag 不存在时提前失败，不能退回默认分支。
- 校验工作流变更不通过发布真实制品来试错：优先静态检查和无发布权限的验证流程；实际发布前另记录 gate、build 的 SHA 和运行链接。
- 验收：A11–A14。

### R6：benchmark 报告的语料与评分口径明确可追溯

- 修改范围在相邻 `moi-benchmark` 仓库，单独提交；目标为 `memoria/evaluate/memoria-longmemeval-locomo-final-summary.md`。
- 分列入库语料 `longmemeval_s_cleaned.json` 与问题／参考答案文件 `longmemeval_oracle.json`，附各自已有 manifest／脚本依据。
- 集中列出被测 commit＋source diff、抽取开关、embedding、Top-K、Reader／Judge、数据集范围、QA 与证据召回的不同分母。
- 保留 Controlled Track、LoCoMo 排除 Category 5、竞品非同环境排名等限制；不更新实验数值，不重跑付费评测，不覆盖原始 run。
- 验收：A15。

## 3. 交付与合并要求

建议拆成 4 个小 PR：R1＋R3（检索）、R2（输入契约）、R4＋R5（CI／发布）、R6（moi-benchmark 文档）。每个 PR 必须列出需求 ID、实际变更文件、命中的用例 ID、执行命令、被测 SHA、结果及未执行项。

代码修复至少保留能在旧实现失败的回归测试；局部测试通过后运行仓库现有必需 CI。数据库用例必须实际连接测试库，测试筛选匹配 0 个用例或环境缺失不能算通过。发布门禁变更须覆盖拒绝路径，不能仅验证成功路径。

粗估 3–4.5 人日，不含依赖 PR 审阅、外部服务等待及环境修复。新增需求或改变兼容性时重新估算。
