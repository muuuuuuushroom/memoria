# Memoria 检索性能改进调研

日期：2026-10-09。目的：为提升检索质量与延迟/成本表现，整理可落地的实验顺序。本文引用外部论文与官方文档作为设计依据；任何论文结果都不代表 Memoria 已获得相同收益。Memoria 当前方案及本地测量口径见 [证据覆盖感知检索设计](memoria-evidence-aware-retrieval-design.md)。

## 论文证据核对

| 论文发现 | 原论文设置与结果 | 对 Memoria 的含义 |
|---|---|---|
| LongMemEval §5.3：事实增强 key 优于单独的事实/关键词 key | 在 LongMemEval-M 上，以 round 为 value 时 Recall@5 从 value-only 的 0.582 升至 `value + facts` 的 0.644；作者跨设置报告 Recall@k 平均提高 9.4%、最终 QA 准确率提高 5.4%。单独用 facts 或 keyphrases 作 key 没有稳定胜过 value。 | 保留完整原始记忆，将有来源的事实拼进检索 key；不要用事实摘要替代原文。论文是特定数据、dense retriever 和 Llama 3.1 8B 抽取配置下的结果，不能作为 Memoria 的预期提升值。 |
| LongMemEval §E.3：索引期合并优于检索期 rank merging | 将 value 与每条派生信息分别建索引、再按 rank 合并，低于把派生事实扩展进同一 key；作者提出并行索引会使规模约增至 `m+1` 倍，可能导致性能差异。 | RRF 留作多路候选互补/排序基线单独消融，不默认“多路投票”优于改善记忆表示。 |
| LongMemEval §5.4、§E.4：明确时间范围有益，错误时间范围有害 | temporal subset 中，round value 的平均 recall 提高 11.3%，session value 提高 6.8%；较弱的 Llama 3.1 8B 会在问题没有时间线索时错误地产生范围并剪枝，GPT-4o 可以选择不生成范围。 | 仅在时间线索明确时启用窄范围过滤；保留宽范围召回回退，禁止不确定解析结果变成硬过滤。论文提升数字不是 Memoria 实测。 |
| NAACL 2025 Sub-Question Coverage：按核心子问题检索有帮助 | 摘要报告增强系统 pairwise win rate 为 74%；Retrieval Augmentation 对原 query 和 core 子问题分别检索、合并候选、按 core 覆盖重排。该胜率是长答案偏好评估，不是 Recall 增幅。 | 只对多部分汇总/多跳问题分解，固定总检索预算并测全部必需证据入选率。 |
| NAACL 2025 KG²RAG：seed 后图扩展在 HotpotQA 上有效 | 论文在 HotpotQA 及变体上验证语义 seed、KG chunk 扩展与证据组织，使用构建好的 Wikipedia 知识图。 | Memoria 关系边覆盖、来源与主体/时间消歧达标后再测；试点图没有关系边，当前不列为近期主线。 |

以上数值按论文自身指标与语料引用，仅用于形成待验证假设。主要来源：[LongMemEval §5.3–5.4、§E.3–E.4](https://arxiv.org/html/2410.10813v2)、[Sub-Question Coverage](https://aclanthology.org/2025.naacl-long.301/)、[KG²RAG](https://aclanthology.org/2025.naacl-long.449/)。

## 建议优先级

### 1. 先拆开候选窗口与最终 K，并消除提前截断

把检索链路中的数量拆成每路候选深度 `W_i`、融合后的候选数 `W_f`、重排深度 `W_r` 和最终返回 `K`。接口/内部 API 应让召回阶段返回可观测的候选并集，再由后续阶段选择最终 K。确保 `W_i` / `W_f` 大于或等于 K；逐级提高它们，直到候选证据召回趋于饱和或延迟预算耗尽。不要预设诸如 50、100 这样的常数为最优值。

依据：Elasticsearch RRF 文档将 `rank_window_size` 定义为每个子检索器参与融合的窗口，要求它至少为最终 `size`；其示例明确展示窗口截断如何排除底部候选。[Elasticsearch RRF 官方文档](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion) 这能支持“窗口是影响候选可见性的独立参数”，不能推出 Memoria 的最佳窗口。Memoria 设计记录还指出当前 hybrid 检索内部截到 K、graph 路由满 K 即早退；需先实测并去除这些召回前截断，再评测融合公式。[Memoria 设计记录](memoria-evidence-aware-retrieval-design.md)

诊断时记录每个 gold memory 在存储召回、各路候选、过滤后、融合后、重排后和最终 K 的去留。区分“从未进入候选池”与“进入候选池但被排序/过滤掉”；后置 reranker 无法恢复未进入候选池的证据。

### 2. 用事实增强索引改善长期记忆的语义可检索性

优先对比 `raw-only` 与 `raw + 有来源支持的 facts` 作为同一条索引 key；不要假设把原文视图和事实视图做两路独立排名一定更好。保留原始记忆作为唯一证据值，派生事实仅用于检索，并记录来源、版本、抽取器版本；冲突、否定、时间、主体和角色要从来源继承。

依据：LongMemEval §5.3 Table 3 中，round value 的 Recall@5 从 value-only `0.582` 到 `value + facts` `0.644`；作者跨设置报告 recall@k 平均提高 9.4%、最终 QA 准确率提高 5.4%。单独使用 facts/keyphrases 并不稳定更好。附录 §E.3 的 post-retrieval rank merging 也低于 key expansion，作者提出并行索引数量增长可能是原因之一。此结果只支持将“原文 + 有来源 facts”设为 Memoria 的高优先级实验假设，不是跨语料保证。[论文全文 §5.3 / §E.3](https://arxiv.org/html/2410.10813v2)。A-MEM 也描述了通过上下文描述和关联索引来增强可检索性，但其完整动态记忆机制不应与此处的轻量索引 key 等同。[A-MEM（NeurIPS 2025）](https://proceedings.neurips.cc/paper_files/paper/2025/hash/19909c36f51abc4856b4560aff3d36d6-Abstract-Conference.html)

### 3. 先把 RRF 做成可解释的基线，再对照分数融合

保留 RRF 作为默认可复现实验组：它只使用各路 rank，避免直接相加尺度不同的 BM25 与 dense 分数。参数扫描至少覆盖每路候选窗口、RRF rank constant 和各路权重；固定候选池/预算进行对照。

另设 calibrated/normalized linear fusion 组：先在开发集对每种 query 类型检查各路分数分布和排序质量，再比较 min-max、z-score 或可校准的分数映射后加权求和。不要把 raw cosine 与 BM25 生分数直接线性相加，也不要把归一化分数当成天然可比或概率。Qdrant 官方文档同时支持 RRF 和 Distribution-Based Score Fusion（DBSF），说明 DBSF 用每路返回分数的均值与标准差归一化后求和；文档指出 DBSF 与加权 RRF 均可能胜出，且没有一种在所有情况下占优，需用评测集选择。[Qdrant Hybrid Queries 官方文档](https://qdrant.tech/documentation/search/hybrid-queries/)

Elasticsearch 文档给出 RRF 对多结果集按排名进行合并的定义及窗口参数；原始 RRF 论文比较了其在论文实验集中的表现，不能据此推断 Memoria 的最佳融合器。[Elasticsearch RRF 文档](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)；[Cormack et al., SIGIR 2009](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)。Memoria 已有 30 题 RRF 试点显示有排序变化但 Recall@20 持平、MRR 略低于 baseline；所以后续重点应是更大、分层、固定预算的消融，而不是宣称 RRF 提升质量。[已有融合试验记录](retrieval-fusion-mini-benchmark.md)

### 4. 在候选池稳定后，测 Cross-Encoder 重排的边际收益

先由 sparse/dense/graph 获得候选并集并去重，再用冻结 Cross-Encoder 对 `query-or-core-subquestion × original memory value` 打分，只重排前 `W_r` 条；分批执行，记录单独耗时和 token/context 成本。比较 `W_r ∈ {K, 2K, 4K, ...}` 的 Recall@K、MRR/nDCG、必需证据完整率和 p95。以质量提升 / 延迟成本曲线选点，不以 reranker 分数阈值代表支持概率。

依据：Sentence Transformers 官方示例将 retrieve-then-rerank 作为两阶段模式，说明 Cross-Encoder 对查询与文档联合打分；文档指出对数千/数百万 query-document pairs 打分会较慢，因此用第一阶段取有限候选再重排。[Sentence Transformers Retrieve & Re-Rank 文档](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html) Nogueira 与 Cho 的 BERT passage reranking 论文提供神经重排的原始研究证据，但其 MS MARCO / TREC-CAR 任务结果不等于长期记忆任务收益。[Passage Re-ranking with BERT](https://arxiv.org/abs/1901.04085)

重排监督目标也要区分“相关”与“支持答案的证据”：对历史事实查询，优先保留主体、时间、条件和来源上下文明确的原始记忆，不用派生摘要替代证据。

### 5. 对复杂问题优化证据集合覆盖，简单问题走低成本路径

将复杂/多部分问题分解成少量直接回答原问题所必需的 core sub-questions。原查询和子问题分别召回，但分配固定的总候选预算；最终 K 采用覆盖感知选择：优先补足尚未覆盖的需求，再按相关性和冗余惩罚决胜。单一事实查询保留原始相关性排序路径，避免无谓分解和延迟。

依据：NAACL 2025 的 Sub-Question Coverage 研究提出区分 core、background、follow-up 子问题，并报告在其开放式问答设置中，用 core 子问题辅助检索和生成优于未使用子问题的 baseline；论文数据集与任务设置不同，不能视为 Memoria 事实记忆上的实测增益。[论文（NAACL 2025）](https://aclanthology.org/2025.naacl-long.301/) Memoria 的具体做法应与“新增 query 带来额外召回预算”分开控制，避免把花更多算力误判为算法收益。

选择器可先用无学习的 greedy marginal coverage 做可解释基线，再对比纯 Cross-Encoder Top-K。覆盖判定记为需求 ID 到 memory ID / 原文 span 的支持关系；不能把 reranker 分数当成证据支持概率。评估最终证据集合完整率、来源支持率、冗余率，并观察简单查询是否退化。

### 6. 仅对真正多跳问题尝试来源图扩展和一次定向补检索

确认当前 graph edges 的来源、版本、主体消歧与时间语义足够可靠后，再从高质量 seed memory 做一跳、定额扩展；扩展结果必须回到原始来源记忆参与重排。子图关系稀疏或实体不确定时关闭扩展。若核心需求仍缺证据，允许仅针对缺口进行最多一次检索，并报告额外延迟和成功补回率。

依据：KG²RAG 的论文流程先语义检索，再利用知识图扩展相关 chunk 并组织证据；这支持把图作为 seed retrieval 的可选补充机制，但不是证明 Memoria 的 backfill links 足以充当事实图。[KG²RAG（NAACL 2025）](https://aclanthology.org/2025.naacl-long.449/) DIVA 在歧义问题的多个解释上检查上下文支持；它处理的是解释歧义，不能与多跳核心需求混为一类，也不能据其结果推断私人记忆可由 closed-book 补全。[DIVA（NAACL 2025）](https://aclanthology.org/2025.naacl-long.56/)

对时间敏感问题，分别记录事件时间、消息记录时间、入库时间。年龄或置信度不宜作为丢弃历史证据的唯一硬条件；应让 query 时间约束与宽范围回退并存。LongMemEval §5.4 报告 round/session temporal subset 的 recall 分别平均提高 11.3%/6.8%，但 §E.4 同时展示弱时间解析模型会在无时间线索时虚构范围并误剪候选。因此应把“是否显式含时间线索”与范围置信度纳入路由；不确定时退回宽范围，不作硬过滤。该数值不是 Memoria 实测。[LongMemEval](https://arxiv.org/html/2410.10813v2)

## 推荐实验矩阵

所有参数只在开发集选取，冻结后在独立测试集报告。固定语料快照、模型版本、每问调用次数、总候选预算和最终上下文预算；另附允许额外预算时的质量—成本曲线。

| 阶段 | 单变量对照 | 核心观测 |
|---|---|---|
| A. 召回诊断 | 当前实现 vs 去除 hybrid K 截断 / graph 满 K 早退；候选窗口 W 扫描 | 各阶段 Candidate Recall、证据进入/丢失位置、p95 |
| B. 表示 | raw-only vs fact-augmented key vs 双视图 | Candidate Recall、历史事实/否定/时间分组召回、写入抽取成本 |
| C. 融合 | RRF 参数扫描 vs calibrated/normalized linear 或 DBSF | Recall@W、MRR/nDCG@K、完整证据率及分组波动 |
| D. 精排 | 无 reranker vs Cross-Encoder，扫描 W_r | 最终证据覆盖、MRR、p95 和吞吐；批处理影响 |
| E. 集合选择 | reranker Top-K vs core-subquery coverage greedy | 必需证据集合完整率、冗余、简单查询退化 |
| F. 条件扩展 | 无图扩展 vs 一跳定额扩展；无 retry vs 一次定向 retry | 新增有效来源证据数、错误跨主体/时间率、补回成功率、成本 |

至少分别报告：Candidate Recall@W、Recall@K、MRR/nDCG、所有必需证据同时入选率、历史状态正确率、来源支持率、重复占比、查询类别分组、p50/p95 延迟、调用次数及 token 成本。由独立 Reader/Judge 或人工标注评答案质量，不从检索指标推定答案准确率。

## 结论

当前最值得先做的是候选池可观测性和窗口/最终 K 解耦，因为它能判断损失源于召回还是排序，并为后续所有算法对照提供可解释基线。之后优先验证 LongMemEval 支持、且与个人长期记忆最贴近的 `raw + sourced facts` 索引 key；再比较 RRF 与校准分数融合，并在候选池稳定后测冻结 reranker。时间过滤仅在条件明确时启用并保留宽范围路径。覆盖选择只针对复杂多部分问题；图扩展等关系图具备足够来源边后再测。所有结果以同预算、独立保留集验证。外部论文收益不写作 Memoria 结果，现有 RRF 小样本不支持“融合已提升检索质量”的结论。
