# Memoria 工程验收报告与测试用例

日期：2026-09-23　报告类型：现状核查＋待执行专项验收

关联：[开发需求](specs/2026-09-23-small-improvements-requirements.md) · [改进清单](memoria-small-improvements.md)

**结论：Memoria 已有 PR 工程测试；本次 R1–R6 尚未开发，不能签署“改进验收通过”。本文只核查已有代码、CI 配置及历史运行证据，未在本地执行产品测试。**

## 1. 现有 PR 工程验收

| 层级 | 已有检查 | 能证明的范围 |
|---|---|---|
| PR 规范 | Conventional Commits 标题检查 | 标题格式合规 |
| Rust 静态检查 | `cargo check`、`cargo clippy -- -D warnings` | 编译与所选目标的 lint，无替代行为测试的能力 |
| Rust 单元测试 | API、core、service、MCP 的 `cargo test --lib` | 被覆盖的解析、协议、纯逻辑等行为 |
| 数据库集成／E2E | MatrixOne service＋`cargo test -- --test-threads=1` | 实际存储、API、MCP、分支和快照等路径 |
| 特定故障回归 | 恢复事务失败、分支探测清理、离线恢复清理单独运行 | 指定的异常与清理路径；部分平时 ignored 的用例被显式启用 |
| OpenClaw 条件检查 | 相关路径变更时 `npm test`、`npm run test:pack` | 插件行为及打包路径，不是每个 Rust PR 都运行 |

配置依据：`.github/workflows/test.yml`、`test-gate.yml`、`test-openclaw.yml`、`pr-title.yml`。

### PR #258 的可核查示例

- [PR #258](https://github.com/matrixorigin/memoria/pull/258)：MCP 工具错误结果修复，查询时状态 OPEN。
- PR head：`8f442c8134ceddbb51d7960fc9a4bd35f0682e2b`。
- [CI Run 35718125530](https://github.com/matrixorigin/memoria/actions/runs/35718125530)：查询结果关联该 head，2026-09-22 完成，Check & Clippy、Unit Tests、DB Tests 均 SUCCESS；标题检查 SUCCESS，Mergify 为 NEUTRAL。
- [DB Tests 日志](https://github.com/matrixorigin/memoria/actions/runs/35718125530/job/106714834014)含实际执行记录，例如 `test_branch_lifecycle_verify_db ... ok`、`test_branch_from_snapshot ... ok`、`test_rollback_nonexistent_snapshot_errors ... ok`，以及显式故障回归步骤的测试结果。
- 日志存在 ignored 用例，不能把 job 绿色解释为所有测试、所有配置均执行。PR 描述中的本地通过数量属于作者报告；上述 CI 状态与日志是本次查询核对的证据。
- 该 PR 是工程验收示例，其通过结果不能充当 R1–R6 的验收证据。

### 当前缺口与未确认项

1. PR／发布测试均使用 MatrixOne `latest`，环境不是固定基线。
2. Rust 手动发布跳过 gate，且 build 接受 gate skipped。
3. 没有在本次检查的 PR workflow 中发现 LongMemEval／LoCoMo 质量门禁。质量 benchmark 与工程回归是不同验收层。
4. `.mergify.yml` 有至少一人批准等条件，但不能仅凭该文件证明 GitHub 强制要求全部 CI。此次 branch protection 查询返回 404、rulesets 返回空列表；权限与配置原因尚未区分，**强制合并保护未确认**。
5. 下文列出的数据库样例在 DB 不可用时会失败，不是静默跳过；仓库另有依赖外部 embedding 或 branch-pick 能力的条件跳过测试。验收仍须记录实际执行前置条件，不能把成功退出自动视为全部能力已测。

## 2. 本次专项测试样例

以下 A01–A15 是待实现／待执行的验收用例，不是假定已经存在的 Rust 测试。复用现有测试目录，不新增测试框架。

### R1：检索分数

**A01：三类候选合并与评分。** 使用固定候选输入，时间分量为 0、置信分量为 1、无反馈，权重沿用现有 0.3／0.2／0.2／0.3。

| 候选 | 向量来源 | 全文原始分数 | 正确总分 |
|---|---:|---:|---:|
| V：向量独有 | 0.8 | 0 | 0.54 |
| F：全文独有 | 无，按 0 计 | 2 | 0.433333… |
| B：两路共同命中 | 0.6 | 1 | 0.58 |

断言：顺序为 B、V、F；B 只出现一次；F 的 explain 向量分量为 0；浮点误差小于 `1e-6`。旧实现会把 F 的原始全文分数 2 当向量分数，使总分变成约 1.033333，此用例必须能够检出。测试必须经过实际合并／评分代码，不能只在测试里重写公式。

**A02：未受影响行为。** 固定同一批向量候选，全文空集合时修复前后分数与顺序相同；Top-K 正确截断。用现有数据库过滤回归确认不跨 user／branch／subject，避免用合成排序测试替代隔离验证。

### R2：输入与零副作用

下表各输入在 embedded MCP、remote MCP 和 REST 三条路径验证；用参数化表复用测试逻辑。

| ID | 输入 memory_type | 预期 |
|---|---|---|
| A03 | `invalid_xyz`、`""`、`"  "`、`null`、数字、数组、对象 | 拒绝；不静默写为 semantic |
| A04 | 字段缺省；六个合法字符串 | 缺省为 semantic；合法值原样保留；正常完成写入 |
| A05 | 任一 A03 输入，content 为非空正常文本 | embedding 调用计数 0、存储写计数 0；remote HTTP stub 收到请求数 0 |
| A06 | 未知工具；合法工具但非法类型；现有只读 key | 未知工具仍为协议错误；非法类型为工具错误；只读 key 不获得写权限 |

MCP 输入样例：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"memory_store","arguments":{"content":"项目使用 Rust","memory_type":"invalid_xyz"}}}
```

预期结构（错误文字不要求逐字相同）：

```json
{"jsonrpc":"2.0","id":1,"result":{"isError":true,"content":[{"type":"text","text":"memory_type 无效；请使用合法类型"}]}}
```

REST 请求体复用上述 arguments；必须是 4xx 校验失败，而非 HTTP 200。测试前后验证目标用户记录不增加；验证零 embedding 不应只靠最终记录数推断。

### R3：故障注入与日志

| ID | 故障／输入 | 必需断言 |
|---|---|---|
| A07 | 全文查询返回受控错误，向量成功 | 向量候选正常返回；每次失败分支有一条结构化 warning，包含稳定降级字段 |
| A08 | 全文成功但零结果 | 无降级 warning；原向量结果不变 |
| A09 | 在注入错误中放入测试哨兵正文／凭据；另测向量失败 | 日志不出现哨兵；向量失败仍按既有错误路径返回，不伪装为正常空结果 |

使用现有测试替身或最小局部注入点，不引入通用故障框架。故障只作用于测试环境；捕获 tracing 输出验证日志内容。

### R4–R5：CI 与发布

| ID | 场景 | 必需断言 |
|---|---|---|
| A10 | 普通 PR 与共享 Test Gate | 两处使用同一固定 digest；SQL 可用后真实 DB 回归通过，记录实际镜像和 SHA |
| A11 | 手动选择 tag T，其提交不同于默认分支 | gate 与 build 都指向 T 对应的同一 commit；测试未完成前不能构建发布 |
| A12 | gate failure／cancelled／skipped | 三种情况分别检查，build／release 均不能启动 |
| A13 | tag 不存在 | 解析失败，不能回退 main，也不能构建 |
| A14 | 自动 tag push；共享 gate 既有调用方 | tag push 仍正常串联 gate→build；Docker 调用方 ref 默认语义未被破坏 |

静态配置检查与真实 Actions 运行分开记录。通过条件矩阵可在无发布权限的验证工作流中测试；本轮编写文档没有触发工作流或发布制品。

### R6：报告一致性

**A15：逐项对照 manifest 和脚本。** 确认入库是 S cleaned、oracle 仅提供问题／参考答案；记录两个文件的角色与已有哈希；Controlled Track、被测代码状态、模型配置、Top-K、LoCoMo Category 1–4、QA／证据分母均明确；实验数字与原产物一致。未下载原语料时标明无法重新核算语料，不补造统计。

## 3. 已有可运行测试样例

以下名称已对照本地源码确认。它们是可复用的回归基线，不是 A01–A15 已补齐的证明。

| 现有测试 | 位置 | 覆盖／限制 |
|---|---|---|
| `test_search_hybrid_access_count_stays_tiebreaker` | `memoria/crates/memoria-storage/tests/store_crud.rs:384` | hybrid 排序回归；不直接覆盖全文独有分数混用 |
| `test_retrieve_with_explain` | `memoria/crates/memoria-api/tests/api_e2e.rs:5117` | 检索 explain 分量；需补 A01 的具体数值断言 |
| `test_batch_store_invalid_type_rejects_all` | `memoria/crates/memoria-api/tests/api_e2e.rs:6313` | REST 批量非法类型拒绝；不替代 MCP／单条路径及零调用断言 |
| `test_graceful_degradation` | `memoria/crates/memoria-api/tests/api_e2e.rs:9526` | 无效／不存在记录处理；名字虽含 degradation，不是全文后端故障注入 |
| `test_snapshot_rollback_restores_state` | `memoria/crates/memoria-mcp/tests/snapshot_e2e.rs:175` | 快照回滚后的状态恢复 |
| `test_correct_on_branch_isolated_from_main` | `memoria/crates/memoria-mcp/tests/branch_e2e.rs:2112` | 分支更正不影响主分支 |

前置条件：Rust／Cargo、依赖可用；专用 MatrixOne 测试实例，测试账号可创建／迁移测试数据库并执行所需快照操作。使用测试数据；相关测试会写数据库。`SQLX_OFFLINE=true` 不代表数据库测试能离线运行。以下连接是仓库默认测试配置，按测试环境调整。

```bash
cd /Users/muuushroom/gitrepos/memoria/memoria
export DATABASE_URL='mysql://root:111@localhost:6001/memoria_test'
export SQLX_OFFLINE=true

cargo test -p memoria-storage --test store_crud test_search_hybrid_access_count_stays_tiebreaker -- --exact --test-threads=1
cargo test -p memoria-api --test api_e2e test_retrieve_with_explain -- --exact --test-threads=1
cargo test -p memoria-api --test api_e2e test_batch_store_invalid_type_rejects_all -- --exact --test-threads=1
cargo test -p memoria-api --test api_e2e test_graceful_degradation -- --exact --test-threads=1
cargo test -p memoria-mcp --test snapshot_e2e test_snapshot_rollback_restores_state -- --exact --test-threads=1
cargo test -p memoria-mcp --test branch_e2e test_correct_on_branch_isolated_from_main -- --exact --test-threads=1
```

按 PR 影响面选择执行，不要求文档 PR 或无关修改跑完所有样例。共用同一个测试实例时串行执行。记录 embedding／LLM 是 mock 还是实际服务；规则与状态验收不依赖付费模型质量。

现有 CI 还显式运行以下故障回归（同一目录和测试环境）：

```bash
cargo test -p memoria-git --lib failed_insert_rolls_back_preceding_delete -- --ignored --nocapture
cargo test -p memoria-storage --lib materialized_probe_cleanup_preserves_unrelated_tables -- --ignored --nocapture
cargo test -p memoria-git --example restore_cleanup -- --include-ignored --nocapture
```

## 4. 验收结果记录

| 需求 | 专项用例 | 当前状态 | 执行 SHA／环境／证据 |
|---|---|---|---|
| R1 | A01–A02 | 未开发、未执行 | 待 PR 提供 |
| R2 | A03–A06 | 未开发、未执行 | 依赖 #258 的错误契约 |
| R3 | A07–A09 | 未开发、未执行 | 待故障注入及日志证据 |
| R4 | A10 | 未开发、未执行 | 待固定 digest 的 CI run |
| R5 | A11–A14 | 未开发、未执行 | 待成功／拒绝路径证据 |
| R6 | A15 | 未修改、未验收 | 在 moi-benchmark 单独提交 |

每项完成后补：实际测试名及命令、被测 commit、前置环境、执行／通过／失败／忽略数量、日志或 Actions 链接、遗留问题。`--no-run` 仅表示编译，测试筛选 0 命中不算通过；环境缺失记“未执行”，不得记“通过”。

合并建议条件：本 PR 涉及的专项用例全部通过，现有适用 CI 通过，reviewer 核对证据与 PR 代码一致。变更 SHA 后重新执行受影响检查。此条件是建议的验收规则，不冒充已经配置的仓库保护规则。
