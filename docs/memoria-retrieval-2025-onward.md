# Memoria 无需自行训练的检索改进：2025 年以来正式发表论文

核查日期：2026-10-09。优先级按与 Memoria 的匹配程度、正式发表场所和工程可验证性确定，不按“最新”排序；不是穷尽综述，没有比较引用量。

## 筛选口径

以 **2025 年及以后正式发表** 为主，场所由官方 proceedings、OpenReview 或 ACL Anthology 核实。部分论文在 2024 年已公开，下表标注；若严格要求首次公开也在 2025 年以后，应排除这些条目。优先 NeurIPS、ICML、ICLR 与 ACL 系列主会，Findings 单列。正式发表提供同行评审依据，不保证方法在 Memoria 上更好。

“无需自行训练”允许使用现成 embedding、LLM 和作者发布的 reranker checkpoint，须区分论文自身训练模型与使用者仅推理。以下方法描述来自论文；落地顺序和 Memoria 数据结构是工程建议，不是论文已验证的结论。

## 优先阅读清单

| 论文与官方发表来源 | 场所 | 首次公开时间口径 | 最值得借鉴的模块 |
|---|---|---|---|
| [A-Mem: Agentic Memory for LLM Agents](https://proceedings.neurips.cc/paper_files/paper/2025/hash/19909c36f51abc4856b4560aff3d36d6-Abstract-Conference.html) | NeurIPS 2025 主会 | arXiv 2025-02 | 上下文描述、关键词、记忆链接 |
| [From RAG to Memory: Non-Parametric Continual Learning for Large Language Models](https://proceedings.mlr.press/v267/gutierrez25a.html)（HippoRAG 2） | ICML 2025，PMLR 267 | arXiv 2025-02 | 原文与事实图结合，过滤事实种子后用 Personalized PageRank 找证据 |
| [Knowledge Graph-Guided Retrieval Augmented Generation](https://aclanthology.org/2025.naacl-long.449/)（KG²RAG） | NAACL 2025 主会，Long Papers | arXiv 2025-02 | 语义种子之后按事实关系扩展、组织原文证据 |
| [PropRAG: Guiding Retrieval with Beam Search over Proposition Paths](https://aclanthology.org/2025.emnlp-main.317/) | EMNLP 2025 主会 | arXiv 2025-04 | 保留上下文的命题与路径搜索；在线搜索无需 LLM |
| [Towards Lifelong Dialogue Agents via Timeline-based Memory Management](https://aclanthology.org/2025.naacl-long.435/)（THEANINE） | NAACL 2025 主会，Long Papers | arXiv **2024-06** | 保留事件演化和因果联系，沿时间线召回历史记忆 |
| [Provence: efficient and robust context pruning for retrieval-augmented generation](https://openreview.net/forum?id=TDy5Ih78b4) | ICLR 2025 主会，Poster | OpenReview **2024-10**；arXiv 2025-01 | 联合 passage 重排与句子裁剪，可直接使用作者 checkpoint |
| [LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory](https://openreview.net/forum?id=pZiyCaVuti) | ICLR 2025 主会，Poster | arXiv **2024-10** | 长期记忆评测；事实扩展索引、时间感知检索、证据提取研究 |

Poster 是这些主会的展示形式，不等于 Findings 或未审稿预印本。LongMemEval 是评测与工程分析参考，不是新的检索器。整套系统的成绩不能直接归因于某个模块。

## Memoria 当前起点

核查基于主 checkout `6247235` 和当时本地改动，本地 graph/hybrid RRF 与批量 backfill 尚未提交。

1. [hybrid 检索](/Users/muuushroom/gitrepos/memoria/memoria/crates/memoria-storage/src/store.rs:6274)各取 `max(3K,20)` 个向量和全文候选，按相关性、年龄和置信度等启发式评分，之后截到 K。外层重排无法恢复内部已经截掉的证据。
2. [graph 路由](/Users/muuushroom/gitrepos/memoria/memoria/crates/memoria-service/src/service.rs:1931)在 graph 命中达到 K 时提前返回。当前本地 RRF 仅在 graph 不足、补充 hybrid 时生效，尚非每个查询都多路统一重排。
3. [backfill](/Users/muuushroom/gitrepos/memoria/memoria/crates/memoria-storage/src/graph/backfill.rs:83)创建 semantic nodes 与 memory/entity links，未在这个流程创建新的事实或传播关系边，且最多读取每用户 500 条记忆。批量写入优化不等于补齐多跳语义；这也不意味着其他写入路径不会产生边。
4. hybrid 同时按年龄衰减时间分和置信度，有效置信度低于 `0.05` 时过滤候选。应区分“当前值已变更”与“旧事实仍能回答历史问题”，不能仅靠年龄判断历史证据价值。
5. 此前 30 题 LongMemEval 小样本中，RRF Recall@5 为 73.33% → 76.67%，Recall@20 为 95% → 95%，MRR 为 0.673889 → 0.671111；没有图边，未运行 Reader/Judge。这只支持局部召回观察，不能证明多跳或最终回答改善。见 [mini benchmark](/Users/muuushroom/gitrepos/memoria/docs/retrieval-fusion-mini-benchmark.md)。

## 具体借鉴方式与边界

### A-MEM：改善记忆的可检索表达

论文用 LLM 生成 contextual description、关键词和标签，用 embedding 找邻近 note，再建立链接和更新派生属性。[论文](https://arxiv.org/abs/2502.12110)；[作者代码](https://github.com/agiresearch/A-mem)。

**Memoria 实验：**保留原文，新增版本化 `retrieval_context` 和关键词索引。例如“还是按上次那个方案”，从当时会话补全项目、方案、参与人和事件时间，命中后返回原 memory 及来源。上下文补全与记忆链接分别消融，不必先复制整个系统。

无需训练模型参数，但有写入时 LLM 成本。仅使用写入当时可见上下文，不从未来消息或测试问题补索引。派生描述可能编造主体、误消解指代，必须保留来源并同步版本、纠错和删除。

### THEANINE：历史召回应保留事实演化

论文组织时间线及相关联系，在检索中保留演化信息，而不只处理孤立记忆。[论文](https://arxiv.org/abs/2406.10996)；[已读版本](https://arxiv.org/html/2406.10996v3)。

**Memoria 实验：**区分当前状态、某时点状态与变更过程。对“我去年在哪个团队”找当时有效的旧记录；对“团队如何变过”扩展前后版本。历史模式不能仅因年龄衰减排除有来源的证据，但仍遵守权限、删除和实际错误标记。

无需参数训练。先做查询时间约束和有限前后事件扩展；论文只覆盖五个对话 session，不能把 lifelong 标题当作已证明无限历史规模的效果。

### KG²RAG：把图用于补全证据

论文先语义召回 seed chunks，再沿 KG 关系多跳扩展 chunks、组织相关证据。事实包含 `(head, relation, tail, chunk)`，可映射回原文。[论文](https://arxiv.org/abs/2502.06864)；[作者代码](https://github.com/nju-websoft/KG2RAG)。

**Memoria 实验：**从已召回 memory 出发，沿带来源的事实关系找桥接记忆，例如“项目 → 当时负责人 → 负责人后来的决定”。让图贡献补充证据，与向量/全文候选统一排序。这比直接替换 activation 更容易验证图找到哪些缺失证据。

无需参数训练，但有关系抽取、实体消歧和建图成本。同名实体不应跨错用户、项目或快照，扩展需保持时间、主体、权限与来源约束。论文主要评测 HotpotQA 及变体，不能直接转用收益数字。

### HippoRAG 2：完整的图检索路线

论文增加 passage/phrase 节点、query-to-triple 检索与 LLM 过滤，再用 Personalized PageRank 传播并返回原文；无合适 triple 时回退 dense。[论文](https://arxiv.org/abs/2502.14802)；[作者代码](https://github.com/OSU-NLP-Group/HippoRAG)。

**Memoria 实验：**来源关系边与覆盖率可靠后，对多跳查询比较 PPR 和当前 activation。设置候选量、路径长度及调用预算，最终返回原 memory，不仅返回抽取或生成的结论。

不训练模型参数，但论文用 DSPy MIPROv2 优化 triple-filter prompt；复用最终 prompt 可避免自行优化。图覆盖不足时，改变传播算法无法恢复缺失关系。文档 QA 的收益也不直接证明中文长期对话收益。

### PropRAG：命题路径替代过度简化的三元组

离线抽取保留上下文的 propositions 并建索引与图，在线用 beam search 找命题路径，搜索本身无需调用 LLM。[论文](https://arxiv.org/abs/2504.18070)；[作者代码](https://github.com/ReLink-Inc/PropRAG)。

**Memoria 实验：**若三元组丢失“当时、仅在某条件下、尚未批准”等限定，试以完整命题为检索单元，附 `source_memory_ids`、时间及主体，沿关系找配套证据。与 KG²RAG、HippoRAG 2 作为替代方案比较，不必全部叠加。

无需自行训练，但离线有 LLM 抽取/embedding 成本，beam search 也有延迟。限定语是否保留、路径是否跨错时间比图规模更值得检查。多跳 QA 效果不等于个人记忆效果。

### Provence：重排与裁剪分别验证

论文联合 passage reranking 与句子级 pruning。作者训练模型，使用者可直接加载[checkpoint](https://huggingface.co/naver/provence-reranker-debertav3-v1)推理。[论文](https://arxiv.org/abs/2501.16214)。

**Memoria 实验：**候选窗口与最终 K 分离，多路融合后用现成 reranker 排序。长 episodic memory 再试句子裁剪，让相同 token 预算容纳更多证据；保留来源 ID、时间和可回溯原文。

论文限制包括英文训练、QA 场景与单 passage 处理。中文 Memoria 应先选适合中文/多语的现成 checkpoint 做基线，不能直接假设 Provence 可迁移。先测重排再测裁剪，防止删掉否定、日期或条件。重排不能补回候选池外的证据。

### LongMemEval：验证长期记忆的证据覆盖

它提供长期对话评测和表示、索引、时间感知检索及阅读阶段分析，可借鉴 round-level 存储、事实扩展索引、时间约束与先提取证据再回答。[官方论文](https://openreview.net/forum?id=pZiyCaVuti)。

**Memoria 实验：**分开归因漏存、索引不可达、候选漏召回、排序淘汰与 Reader 误读。多跳统计所需证据是否全部入选，时间问题检查命中的事实是否属于指定时期。它是评测/工程研究参考，不是单一新检索算法。

## 推荐实验顺序

| 顺序 | 变更与依据 | 验证重点 |
|---|---|---|
| 0 | 候选窗口与 K 分离；对照 graph 早退和多路并集 | 候选 Recall@窗口、最终 Recall@K、延迟；路由与融合公式分开消融 |
| 1 | 现成 reranker 与 A-MEM 上下文索引分别实验 | 固定候选测排序，固定检索器测索引，最后才组合 |
| 2 | THEANINE/LongMemEval 时间约束及历史证据处理 | 当前值、历史值、变更过程分组，时间/主体错误率 |
| 3 | KG²RAG 式有限证据扩展 | 完整证据集合召回、桥接关系准确率、图覆盖率 |
| 4 | HippoRAG 2 PPR 或 PropRAG 命题路径 | 多跳答案支撑率、p95 延迟、建图与推理成本 |

这是便于验证的顺序，不是认定方法一定有效。先确定失败来自对应层，避免完整照搬系统。

## 防止过拟合评测集

- 冻结语料快照、模型版本、时间与权限边界；索引不能使用测试问题、答案或未来消息。
- 在开发集确定候选窗口、prompt、时间路由与重排参数，独立测试集用于最终验证；反复看测试失败调规则后，不能继续把该集视为未见测试集。
- 优先按用户、项目、会话来源分组划分，另留时间外推与领域外测试；近重复记忆和派生摘要不要跨开发/测试泄漏。
- 保持证据单位和上下文预算一致，逐模块消融，报告 Recall、MRR/nDCG、完整证据覆盖、答案支撑率、时间/主体错误及延迟成本。
- 不用当前 30 题选最终方案；扩大覆盖并报告不确定性、失败分组与未改善任务。本次没有新实验或新收益数字。

## 降低优先级的参考

[LightRAG](https://aclanthology.org/2025.findings-emnlp.568/)正式发表于 **Findings of EMNLP 2025**，首次公开在 2024 年，不能写成 EMNLP 主会。

[Zep](https://arxiv.org/abs/2501.13956)与 [Mem0](https://arxiv.org/abs/2504.19413)可作为工程参考；本次未核实上述主会发表证据，所以不纳入主会清单，也不据此断言没有其他正式发表版本。

先前列举的 [Co-Evolving Graph and Text Memory](https://arxiv.org/abs/2607.23278)、[Stashbird](https://arxiv.org/abs/2609.34242)、[Finding the Right Balance](https://arxiv.org/abs/2610.09412)与[有界记忆评测参考](https://arxiv.org/abs/2610.00366)仅保留为探索性预印本线索；本次未核实高认可度场所录用，不与主表等量齐观，也不作为当前改造的主要依据。

主要发表证据为主表官方链接。本次仅更新研究记录，未修改产品代码或启动服务。
