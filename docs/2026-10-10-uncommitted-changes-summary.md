# Memoria 未提交改动总结（2026-10-10）

本文记录当前工作树，便于后续审阅与分批提交。核查基线是个人 fork 当前本地 snapshot `6247235e27bc62898b122473dafae084bea61c80`；用户提供的 live upstream `main` 已到 `5ec53a8`，该对象不在本地仓库，工作树没有自动 fetch/rebase 到它，相关实现不应描述为已与最新 upstream 对齐。核查时有两个已跟踪 Rust 文件被修改，`benchmarks/fusion/` 和下述研究、设计文档尚未跟踪。本文没有修改产品代码、启动服务、重跑付费评测或提交代码。

**当前产品代码包含条件 RRF 融合与批量 backfill v2；全通道 RRF 仅作为独立实验补丁保存。证据覆盖感知检索仍是设计方案。** 检索实验结果不能作为最终回答准确率或新设计收益。

## 1. 两个核心 Rust 文件

### `memoria/crates/memoria-service/src/service.rs`

原先在图候选不足时补充 hybrid 结果，按 `memory_id` 去重、取较高的原始分数，再混合排序。图 activation 总分与 hybrid 综合分数没有共同尺度，直接比较会把不同评分含义当作同一数值。

新增 `fuse_graph_hybrid`，分别按每路有限原始分数降序排序，同分按 `memory_id` 决定顺序，再在每路内去重。每个唯一候选按一基名次累加 `1/(60 + rank)`；双路命中各贡献一次。最终按融合分降序、ID 作为同分规则，截取 Top-K，并把融合分写入返回记忆的 `retrieval_score`。非有限原始分数按缺失处理；空列表和零上限有明确行为。

`CandidateScore` 新增可选的 `graph_rank`、`hybrid_rank`、`graph_score`、`hybrid_score`。融合路径的 verbose explain 与最终返回结果逐项对齐，同时保留 hybrid 的 vector/keyword/temporal/confidence 分量；非融合路径新增字段为 `None`，序列化时省略。

新增三个纯逻辑测试：尺度变化不影响跨路排序、每路重复与双路交集只计一次、空上限及非有限分数稳定处理。其余若干行是 rustfmt 格式变化。

**路由边界：** graph 已满 Top-K 仍直接返回，未请求 hybrid；只有已有的 partial graph + hybrid 路径调用该函数。graph 为空/失败时沿用 hybrid 回退，现有 session/subject/type/branch 与 embedding 门控保持原流程。当前文件没有 `RRF_ALL_CHANNELS` 或可调通道权重，不能据全通道实验宣称这些能力已经进入主工作树。

### `memoria/crates/memoria-storage/src/graph/backfill.rs`

原流程逐记忆创建 graph node，再逐实体 upsert；实体或 link 写入失败可能被忽略，而 node 已存在会让后续重试跳过该记忆。新流程先收集缺少 node 的记忆，再用规则 NER 形成整个用户批次的 entity/link 计划：小写实体名去重，首次可存储实体的原始 `entity.name` 与类型保留，每个不同的 memory/name 关联保留一次。

计划阶段按 Unicode 字符数拒绝超过数据库长度的实体：规范名和显示名最多 200 字符、类型最多 20 字符。无效实体记录 warning 并跳过，合法实体继续处理；不会截断实体名，也不会把截断后的名关联到记忆。这是批量版 v2 对长 data URI 引发 ID 解析失败的修复。

复用已有 `batch_upsert_entities` 与 `batch_upsert_memory_entity_links`，集中解析实体 ID，再批量写 links。实体写入、缺失 ID 或 link 写入错误向上传播；仅在这些写入全部成功后创建 graph nodes，让 node 表示该记忆 backfill 完成。失败后的部分 entity/link 写入可通过原有 upsert 再次执行。

新增八个测试覆盖：首条元数据与全部记忆关联、与顺序 NER 的实体/link 集合等价、长 data URI 不丢合法 links、Unicode 长度与小写扩展边界、非法首条不遮蔽合法重复项、实体写失败与 ID 重用、link 失败后重试、ID 不完整时禁止写 links。

**保留的限制：** 每用户只读取最多 500 条 active memories；node 查询与创建仍顺序执行；没有 entity/link/node 跨批次事务或同用户并发锁。已存在 node 的记忆仍跳过，因此不会自动修复旧版本已丢失的 links。此流程没有新增 entity graph nodes 或关系边，`edges_created` 仍为 0；批量写入不等于实现多跳建图。

## 2. `benchmarks/fusion/` 的资产与实验边界

### 脚本与配置

| 文件 | 用途与前提 |
|---|---|
| `README.md`、`pilot-manifest.json`、`prepare.py` | 30 题 LongMemEval-S pilot；seed `20261008`，六个类别各五题。manifest 保存公开数据、oracle 与 tokenizer URL、字节数和 SHA256。prepare 下载缺失资产并重新生成 manifest；应核对记录的哈希，不能把远端 `main` 当作永不变化的版本。 |
| `compose.yml` | 固定 MatrixOne 镜像 digest，SQL 端口 `16001`，独立命名的数据/log volumes。只启动数据库，不负责构建或启动 Memoria API、embedding 服务。 |
| `run_pilot.py` | 包装相邻 `moi-benchmark` 的 LongMemEval ingest/retrieve/evaluate 脚本，提供 dry-run、ingest、baseline、modified；API `18100`、Top-20。调用前必须准备配置、API、二进制及所需 Python 依赖。 |
| `run_full_retrieval.py` | 串行、可恢复的完整 LongMemEval-S 500 题与 LoCoMo 1,540 题检索调度；使用相邻仓库脚本、`runtime/embed-venv`、保存的 baseline/RRF binaries、MaaS proxy `18200` 和 API `18100`。会切换 API、保存状态与运行来源，并设置评测用过滤/抽取/治理开关。 |
| `run_all_rrf_experiment.py` | 在冻结的 500 题语料和 graph checkpoint 上运行全通道 1:1、1:2；独占 API `18101`，两路深度各 20，RRF 常数 60。验证外部 LoCoMo 进程暂停状态，预热查询、核对 provenance、重置访问计数、检查快照完整性与稳定性，结束后恢复记录的进程。它依赖本地暂停记录及实际进程，不是新机器可直接执行的通用入口。 |
| `analyze_all_rrf.py` | 从四组已完成运行生成 JSON/Markdown 对照；不请求 API、不改原运行目录。核对 500 成功/0 失败、20 条结果、ID 对齐、稳定性及来源哈希，按 Baseline 路由分层，计算配对 bootstrap 与纯 hybrid 反事实。支持 `--runs-root` 和 `--output-prefix`。 |
| `maas_batch_proxy.py` | OpenAI 兼容 MaaS BGE-M3 1024 维批量/SQLite 缓存适配；重试暂时错误，批量输入拒绝时拆成单项，避免一个无效文本丢掉其他输入。 |
| `embedding_server.py` | 另一个本地 FastEmbed ONNX 服务选项，默认 BGE-M3、1024 维、`max_length=512`；其截断、实现与 MaaS 结果不能默认等价。 |

`.gitignore` 排除 `assets/`、`runtime/`、logs、缓存、`__pycache__/` 和 `*.env`。本地 `runtime.env` 存放 endpoint/凭据，未进入候选提交。运行二进制、模型、SQLite 缓存、完整日志和状态也不在 Git 跟踪范围；新增目录的简短 README 是 pilot 说明，并未覆盖全实验的完整环境安装与构建流程。

### 已保存结果

| 记录 | 已记录结论 |
|---|---|
| `results-summary.json`、README | 初次 30 题 pilot：1,410 chunks 入库 1,407 memories，三个输入被既有控制拒绝；1,144 graph nodes、0 edges。两组均 30/30 Top-20，路径为 graph 4、graph+vector 10、hybrid 16，10 题顺序变化。初次 Recall@20 为 0.941667。文件另保留 calibrated 运行，不能与初次指标混用。 |
| `results/lme-rerun-comparison.json` | 另一次 30 题重跑：Baseline/RRF Recall@20 均 0.95，Recall@5 为 0.733333/0.766667，MRR 为 0.673889/0.671111；10 题顺序变化。小样本不支持整体质量提升，也没有 Reader/Judge 或多跳关系边验证。 |
| `results/native-*-v2-rrf.json` | 原生 core-v2 15 场景得分 69.44，graph-entity-v2 10 场景 57.83，large-graph-v2 2 场景 0。这里只有 RRF 结果，不能构成优化前后因果比较；原生 scorer 不敏感于排序，排名比较应看 LongMemEval 指标。 |
| `results/all-rrf-comparison.{json,md}` | 四组完整 500 题运行通过记录中的完整性/稳定性门槛；质量只计算 470 道非拒答题的会话证据检索。报告含来源哈希、执行/构建配置、基线路由分层、配对 CI 与离线纯 hybrid 诊断。 |

完整 500 题对照的主要指标如下；它们属于本轮 fusion 数据快照，不能与 `memoria-resume.md` 引用的历史 Controlled Track 系统成绩混为一组。

| 变体 | Recall@20 | Complete Recall@20 | Hit@1 | MRR@20 | P50/P95 ms |
|---|---:|---:|---:|---:|---:|
| Baseline | 0.9641 | 0.9255 | 0.6957 | 0.7914 | 553.2 / 1557.8 |
| 条件 RRF | 0.9695 | 0.9383 | 0.6830 | 0.7850 | 1185.4 / 2870.1 |
| 全通道 1:1 | 0.9695 | 0.9383 | 0.6830 | 0.7860 | 708.9 / 2749.7 |
| 全通道 1:2 | 0.9641 | 0.9255 | 0.6489 | 0.7652 | 512.1 / 1657.3 |

全通道 1:1 相对 Baseline 的 Recall@20 提高 0.54 个百分点（95% CI `[+0.04,+1.11]`），Complete Recall 提高 1.28 个百分点（`[+0.21,+2.55]`）；Hit@1 与 MRR 的区间含零。1:2 的 Recall 不变，Hit@1 与 MRR 分别下降 4.68、2.61 个百分点，区间支持退步。CI 为同 question_id 配对重采样，seed 42、5,000 次，未做多重比较校正。

条件 RRF 查询缓存为冷，不能公平比较其延迟；新两组均预热，且顺序运行未随机化，因此延迟只能描述观察。`k=60`、各路 20 条、权重 1:2 时，hybrid 第 20 名的独占得分 `2/80` 高于 graph 第 1 名的 `1/61`；报告核验 500 题最终集合均为 hybrid 的 20 条，graph 此时只能重排而不能补召回。离线纯 hybrid 反事实没有另跑 API、没有独立延迟。

### 构建 provenance

`build-provenance/` 保存基线 commit、完整补丁、编译命令、工具链/dev profile、部分源码与二进制哈希；旧构建记录是历史链条，不应把其中早期哈希当作最终 binary 哈希。

| 构建阶段 | 补丁组合与记录 |
|---|---|
| 全量初版 | `full-build.json`：base `6247235`；baseline 用 `full-common.patch`，条件 RRF 再加 `full-rrf.patch`。common 是评测兼容改动（Top-K 1..200、敏感度开关），未包含于当前两个核心 Rust diff。 |
| 批量 backfill v1 | `full-batch-build.json` 加 `full-batch-backfill.patch`，保存前版 binaries 与写入行为/限制。 |
| 批量 backfill v2 | `full-batch-build-v2.json` 使用 `full-batch-backfill-v2.patch`，最终 baseline/RRF binary SHA256 分别为 `5464330acbaff0608cb6a54d8b30c924b9002dc76ea130914ea6bd8bb29d414b` / `feb133991f8e71181ae441387de22f774a926db378304885907141a8bd12e5ac`。 |
| 全通道 RRF | `all-rrf-build.json`：`full-common.patch` + backfill v2 + `all-rrf-service.patch`；binary SHA256 `779ee922203c23d3ea3d81d7073ccdac30163f5d11753597fbe0dbae348e205d`。全通道 service patch 已含条件 RRF，不能再叠加 `full-rrf.patch`。 |

本次核对当前源码 SHA256：service 为 `91cf3304a7ccba586ccb101be135e7f766788ff10987a0598bedf3dc6d09befc`，backfill 为 `186059608a5e0a75ea3a106e6dcd5441af8d3bcffb7d22cb5341595ac8ea92ea`，与条件 RRF/v2 对应记录相符；五份 patch 的 SHA256 均与 JSON 记录相符。全通道 service 记录哈希为 `dba691777d7c43835c9c6cc19a1d79616ba6cda554ccf61c5432eecf44d98bfb`，明确不同于当前 service 文件。

## 3. 新增研究、设计与说明文档

| 文档组 | 文件与定位 |
|---|---|
| 当前系统与评分问题 | `memoria-methodology.md` 解释记忆表示、写入、hybrid/graph、版本管理及评测边界；`hybrid-score-bug-example.md` 与 `examples/hybrid-score-mock.rs` 提供全文分被误当向量分的标准库 mock。mock 不调用生产函数，不能替代产品回归。该评分问题涉及 `store.rs`，本次两个 Rust diff 不是这一修复。 |
| 融合依据与实验 | `retrieval-fusion-research.md` 核查 RRF/加权融合论文及适用限制；`retrieval-fusion-implementation-references.md` 固定 Qdrant/Weaviate/Graphiti commit，并区分零基/一基常数；`comparable-retrieval-systems.md` 对照 Graphiti/Zep、Mem0、LightRAG 等实现；`retrieval-fusion-mini-benchmark.md` 记录资产、试点与推荐矩阵。 |
| 后续检索研究 | `memoria-retrieval-2025-onward.md` 整理 2025 年以来正式发表论文；`memoria-query-coverage-literature.md` 核查两篇 NAACL 2025 覆盖/歧义论文；`memoria-training-free-rag-options.md`、`rag-retrieval-training-research.md` 区分无需自行训练与需要训练的方案；`retrieval-performance-research.md` 建议先拆候选窗口/最终 K，再测事实增强、融合、reranker、覆盖与来源图扩展。论文数字均不是 Memoria 收益。 |
| 待实现设计 | `memoria-evidence-aware-retrieval-design.md` 提出事实增强 key/原始证据 value、有限核心子查询、时间条件召回、来源扩展、重排、预算内覆盖选择与最多一轮补检索。明确状态为方案设计、未实现、未获得新效果数字；需独立开发集/测试集与逐模块消融。 |
| 小改进需求与验收 | `memoria-small-improvements.md`、`memoria-small-improvements-acceptance.md`、`specs/2026-09-23-small-improvements-requirements.md` 是 9 月 23 日的六项建议、开发需求及待执行验收。包含历史 PR/CI 核查，不能把“验收用例已写”当作 R1–R6 已实现通过；后续实施前应逐项核对当前代码，更新历史状态。 |
| 简历叙事 | `memoria-resume.md` 区分个人 MCP/检索贡献、未提交 RRF、待实现设计与系统级历史成绩；其中 RRF 数字主要引用 30 题试点，未覆盖本目录较新的全量结果。正式发布前应选定运行口径并核对个人贡献来源。 |

## 4. 可复现性与验证状态

**可在具备记录资产后离线复算：** mock 评分算例，以及 `analyze_all_rrf.py` 对冻结四组运行的质量、配对 CI、路由分层与反事实指标。后者仍依赖相邻 `moi-benchmark` 的 evaluator 和原始 `retrieval.jsonl`、manifest、summary、metrics、execution-provenance；当前 Git 候选只包含汇总及来源哈希，单独克隆 Memoria 不能从汇总重建全部逐题证据。`docs/examples/hybrid-score-mock.rs` 可直接按其说明用 `rustc --test` 编译，属于生产代码之外的复现样例。

**可按来源重建、但不具备一条命令全流程复现：** provenance 给出 base commit、补丁组合、工具链与 build 命令；pilot 给出资产 URL、哈希、固定抽样与 ingest/retrieve 入口。API/embedding 启动、依赖安装、MaaS 配置、数据库状态与 checkpoint 仍需外部准备。全量脚本写死相邻仓库和本地 runtime 路径；全通道脚本还依赖历史暂停进程。重新运行需使用隔离的新运行目录/用户前缀，并显式记录新的 binary、数据、配置、图快照及缓存条件，避免混入旧记录。

**已有历史验证记录：** provenance 报告 cargo build、rustfmt/diff check 通过；全通道构建记录报告七个 focused service tests 及 Python 状态/恢复/完整性/拒绝模拟通过。批量 backfill v1 记录五个测试新增但将执行交给父任务；v2 记录三个新增边界测试及两组构建通过，未在该 JSON 提供八个测试的最终执行输出。不能仅据测试存在断言当前工作树八项全部运行通过。

ignored runtime 的 `graph-speedup-verification.json` 记录一个用户 backfill 后 55 nodes、实体/links 数量保留、非法 links 与不匹配 nodes 均为 0。`graph-speedup-timing.json` 的旧中位数 36.062 秒与新 7.9815 秒来自不同题目的观察样本（62 对 10），不能写成严格配对的性能提升。runtime 中全通道调度最后记录 `complete`，但完整 LME/LoCoMo 调度 `full-execution-state.json` 最后记录 `failed`；全通道 500 题成功不等于整个 LoCoMo 或 Reader/Judge 已完成。

**本次总结实际执行：** 阅读工作树 diff、脚本与文档，核对源码/patch 哈希、Git ignore 边界；`git diff --check` 通过。随后在 `memoria/` 下执行两个 crate 的完整 lib tests：

```sh
cargo test -p memoria-service -p memoria-storage --lib
```

结果：命令通过。`memoria-service`：68 passed、0 failed、0 ignored；`memoria-storage`：59 passed、0 failed、1 ignored（MatrixOne disposable DB 用例）。本工作树三个融合测试和八个 backfill 测试均通过；全通道补丁的七个融合测试属于另一个构建状态。数据库重试、真实字段长度、node 完成标志与已有数据兼容性仍需单独集成验证；本次唯一 ignored 用例明确要求 `DATABASE_URL` 和 disposable MatrixOne。Git 配置未设置自定义 `core.hooksPath`，`.git/hooks/` 只有未启用的 sample hooks。

## 5. 建议提交边界

1. **条件 RRF 产品改动：** 只提交 `service.rs` 的融合、explain 与三个测试，按现有门控描述行为。全通道配置、权重和路由另作实验/后续产品 PR；如要采用它们，先明确替换当前代码与验收范围。
2. **backfill 批量与 v2 健壮性：** 独立提交 `backfill.rs` 和八个测试，描述错误传播与完成标志顺序，保留 500 条/事务/并发/旧 links 的限制；不宣称新关系边或已证明多跳收益。
3. **fusion 实验资产：** 将可提交的脚本、配置、manifest、结果与 provenance 作为独立基准包提交；保留 base/patch/binary/原始 run 哈希及不同缓存条件。补充完整复现说明后再称可端到端复现。runtime、模型、下载语料、凭据、缓存和本机 binaries 按当前 ignore 继续留在本地。
4. **研究与设计：** 方法、文献、融合对照与 evidence-aware 设计单独文档提交；建议明确引用日期、固定源码版本和待验证状态。历史小改进需求/验收与简历材料可分别提交，先消除历史状态、旧试点数字与最新结果的误混。

相邻 `moi-benchmark` 的脚本和原始 runs、独立 `memoria-fusion-baseline` 构建状态属于其他仓库/工作树，不由本次 Memoria 文档提交带入。本文只创建本文件，保留其余已有改动，不执行 commit/push。
