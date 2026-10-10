# Memoria 检索融合：原始论文、成熟方案与适用边界

核对日期：2026-10-08。代码上下文由本次主审代理基于 `origin/main` 的 `6247235` 提供；本笔记负责文献核实与方案推导，不代表已完成改造或效果验证。

## 结论

Memoria 当前的问题不只是“两个分数范围不同”。graph 分数混合了语义锚点、传播激活、置信度、重要性、类型偏好、时效与冲突惩罚；hybrid 分数混合向量、关键词、时效、置信度和反馈。即使都映射到 `[0,1]`，相同数字也不表示相同相关性。直接取两路分数的最大值、再混排，缺少可比性依据。

一个**假设算例，并非实测结果**：graph 基础分 `0.35×0.8+0.35×0.6+0.20×0.7+0.10×0.2=0.65`，类型系数和新鲜度均为 1，再应用实体 boost `1.8` 后为 `1.17`；hybrid 的 `0.3×0.9+0.2×0.8+0.2×1+0.3×1=0.93`，反馈系数为 1。`1.17>0.93` 只能说明两套规则给出了这些数字，不能推出前者更能回答查询。大于 1 本身不是 bug，缺少共同评分语义才是核心。

建议以**两路充分召回 → 候选去重并保留来源 → RRF 基线 → 同一最终评分器重排**为评估路线。RRF 适合先消除跨路量纲问题，统一重排适合进一步区分“文本与查询相关”和“经由图关系可提供必要证据”。归一化加权融合也值得作为对照，不应先验认定它不如 RRF。所有优劣需要 Memoria 自身查询与标注验证。

在此之前，必须明确 graph 满额即提前返回的策略：它意味着 hybrid 根本没有参与，而不是“两路已经融合”。融合公式无法找回从未进入候选池的记忆。

## 已核对的论文

### 1. RRF 原始论文（SIGIR 2009）

Gordon V. Cormack、Charles L. A. Clarke、Stefan Büttcher，*Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*。[作者公开 PDF](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)，[DOI](https://doi.org/10.1145/1571941.1572114)。本次已读取全文。

基本做法是只使用每一路的名次，不使用原始分数：

\[
S_{RRF}(d)=\sum_{i:d\in L_i}\frac{w_i}{c+r_i(d)}.
\]

原始方法等权，`w_i=1`；加入权重是工程扩展。名次从 1 开始，未在一路候选列表出现的文档不贡献该路分数。这里用 `c` 表示平滑常数，避免与最终返回数量 `K` 混淆。

论文在 pilot 实验中选定 `c=60`，之后固定该值，在 TREC 与 LETOR 3 上报告了有竞争力的融合效果。**这不是“60 对任何列表长度都最优”的证明，也不是“任何融合都必然超过最好单路”的保证。**原文结果中也存在例外与没有显著优势的对照。

对 Memoria 的直接价值：graph 的 `0.8` 和 hybrid 的 `0.8` 不再被当成同一个量。但它保留了两路内部排序的偏好，也丢失了分数差距：一路第一名只比第二名高一点，和高很多，在 RRF 中相同。

**短列表尤其需要测参数。**若每路只有 5 个候选、`c=60`，第一名贡献 `1/61≈0.01639`，第五名贡献 `1/65≈0.01538`；两路均排第五的文档贡献 `2/65≈0.03077`，超过只在一路排第一的 `1/61`。这是公式推导，不是实测结论：此时“被两路命中”可能远比一路内部前后次序重要。

graph 与 hybrid 又共享向量、词法等信号，不能把双路命中机械解释为两份独立证据。RRF 不要求概率独立，但相关通道可能重复奖励同一信号。应记录重叠比例，并比较等权与可调权重；不要把 graph、hybrid、hybrid 内部 dense、lexical 四份高度重叠的列表直接全部等权相加。

### 2. 加权融合与 RRF 的系统分析

Sebastian Bruch、Siyu Gai、Amir Ingber，*An Analysis of Fusion Functions for Hybrid Retrieval*。[arXiv 2210.11934](https://arxiv.org/abs/2210.11934)，[已读取的 v2 全文](https://arxiv.org/html/2210.11934v2)，[DOI](https://doi.org/10.1145/3596512)。预印本初版 2022 年，v2 为 2023 年；TOIS 在线发表 2023 年，卷 42 第 1 期纸本日期 2024 年。

论文比较 lexical + semantic 的凸组合与 RRF。在其模型、数据和评估协议下，调参后的凸组合具有良好样本效率，并在域内、域外实验中优于所比较的 RRF；作者也发现 RRF 对参数敏感。它纠正了“RRF 完全不用考虑参数”的过强表述。

\[
S_{CC}(d)=\alpha N_s(s_s(d))+(1-\alpha)N_l(s_l(d)),\quad 0\leq\alpha\leq1.
\]

两个关键适用限制：

- 论文 §3.1–3.2 先形成两路候选并集，再为缺失的一路补算分数，然后融合。仅因候选未进该路 top-k 就填零，并不是相同实验协议。Memoria 若采用统一特征重排，也应区分“测得为零”“缺失”“没被这一路召回”。
- 主要报告 Recall@1000、NDCG@1000，小数据集采用 @100。其结果不能直接推广到 Memoria 很短的记忆列表，尤其不能把 lexical/dense 上的结论无条件推广到已混入业务先验的 graph 总分。

论文讨论不同线性归一化下可得到排名等价的凸组合，并不意味着使用同一个固定 `alpha` 就能随便替换归一化，也不意味着这些分数已经成为相关概率。

### 3. 图检索的补充参考：HippoRAG 2（ICML 2025）

Bernal Jiménez Gutiérrez 等，*From RAG to Memory: Non-Parametric Continual Learning for Large Language Models*。[论文与版本信息](https://arxiv.org/abs/2502.14802)，[已读取全文](https://arxiv.org/html/2502.14802v2)，[作者代码](https://github.com/OSU-NLP-Group/HippoRAG)。

它把 passage 更深入地纳入图结构，以 embedding 为 passage 和 triple 提供检索信号，通过 LLM 过滤不相关 triples，再利用 Personalized PageRank 检索。它的启发是：图结构负责发现单独文本相似度可能漏掉的关联证据；判断图结果是否有用时，要保留关系与上下文。

这是一项图检索架构研究，**不是“把 graph/hybrid 总分做 RRF”的论证**。不能把其论文报告的收益当作 Memoria 更换融合公式的预期收益，也没有必要为修复分数混排而直接替换整个架构。

## 成熟产品如何处理

| 方案 | 一手来源与已核对事实 | 对 Memoria 的借鉴 |
| --- | --- | --- |
| Elasticsearch RRF | [官方文档](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)：独立执行 child retrievers，以名次融合；`rank_constant` 默认 60；`rank_window_size` 控制各路候选窗口，最后裁成响应 `size` | 区分召回窗口与最终 K，保留每路名次和融合解释。文档的“requires no tuning”应理解为可用默认值启动，不能否定论文对参数敏感性的实证 |
| Elasticsearch linear retriever | [官方文档](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrievers/linear-retriever)：先按各路 normalizer 处理，再做 weighted sum；支持 `none`、`minmax`、`l2_norm` | 归一化加权融合是正式产品支持的另一条路线；需要显式权重、归一化与候选窗口契约 |
| Azure AI Search | [官方文档](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)：多路检索后 RRF；semantic ranking 在 RRF 之后发生，`@search.rerankerScore` 与融合分数分开返回；支持调试 subscores | 候选融合与最终相关性重排分层；不把所有分数叫成同一个无法解释的 `score` |
| Sentence Transformers | [官方仓库 Retrieve & Re-Rank 文档](https://github.com/huggingface/sentence-transformers/blob/main/examples/sentence_transformer/applications/retrieve_rerank/README.md)：先召回如 100 个候选，再对 query-document 对用 CrossEncoder 重排 | 一套评分器比较候选并集。100 是示例而非通用最优参数；实际数量和模型需由延迟与质量预算决定 |

上述产品资料用于确认工程模式，不构成 Memoria 上的效果证明。文档是滚动版本，本文记录的是核对日可访问内容。

## 归一化、校准与统一重排的区别

**归一化**改变数字尺度，例如候选列表内 min-max：`(s-min)/(max-min)`。它通常保留该列表内部顺序，但不会证明最高分真的相关。即使一路全部不相关，它仍可能把其中最高分映射为 1；单条候选或所有分数相等还需要明确定义退化行为。对同一查询，改变候选窗口也可能改变归一化结果。

**校准**要求先确定目标，例如“这条记忆是回答此查询所需证据的概率”，再依据标注拟合并验证分数到目标的映射。把值压到 `[0,1]` 不是校准；同一范围不等于同一语义。点击、使用反馈还可能受展示位置影响，不能未经处理就当作无偏相关性标签。

**统一重排**让候选在相同特征和规则下竞争。对 Memoria，可对候选并集计算共同的 query-text 相关信号，同时保留 graph activation、路径、实体匹配、证据来源、时效、置信度、冲突状态等独立特征。现有 graph 总分不是纯语义分数；传播节点没有 anchor semantic 分数，也不意味着它不能提供间接证据。只用裸文本 CrossEncoder 可能错误压低多跳桥接记忆，应比较是否需要输入路径说明或加入结构特征。

同一 embedding 的距离变换也应统一定义：给定代码上下文，graph anchor 使用假设向量归一化的 `1-L2²/2`，hybrid 使用 `1/(1+L2)`。即使两种变换在一定条件下保持相同次序，数值与分差仍不同，不能直接当同一特征相加。是否满足单位向量假设需另外验证。

新设计还应防止重复应用先验：若 graph 与 hybrid 都已奖励 recency/confidence，融合之后再不加区分地奖励一次，就改变了这些信号的实际权重。对失效、冲突、权限等有明确产品语义的条件，应先确定哪些是硬过滤、哪些是排序偏好，而不是期待融合算法自行解决。

## 适用于 Memoria 的验证顺序

1. **先观测候选与门控。**记录每路是否运行、候选 ID、原始分项、名次、去重前后数量、重叠比例、graph 满额提前返回比例。纯 graph 返回、纯 hybrid 返回与 fallback 混合返回分开分析。
2. **固定候选并集比较融合。**让 graph 与 hybrid 各取大于最终 K 的候选窗口，对同一候选并集比较现有混排、等权 RRF、可调权 RRF、归一化凸组合、统一特征/模型重排。明确缺失分数的处理方式。这一步避免把召回变化误认为融合收益。
3. **再测端到端路由。**单独比较原有 graph-first 门控与双路召回；可评估并行执行，但需检查资源争用和共享副作用。调整召回窗口、RRF 常数、权重时都记录 latency、候选量和退化路径。
4. **评估次序而不只评估集合。**现有 benchmark 的 substring relevance、precision/recall/noise rejection 不足以判定排序改进，应加入有标注的 NDCG@K，单一关键记忆查询可另报 MRR。多跳任务还应检查必要证据是否成套进入上下文；仅有 MRR 不足以覆盖它。保留 Recall@候选窗口以区分“没召回”与“重排排丢”。
5. **按任务分层并保留独立测试集。**至少覆盖精确实体/关键词、语义改写、跨记忆关联、最新事实与冲突、低置信噪声，以及无相关记忆。小样本先用于诊断和调参，不能同时作为最终优越性的证据。

因此，短期可以把 RRF 当作成本很低、可解释的基线；中期重点是充分召回后统一评分，并保留图证据的作用。是否最终选择 RRF、凸组合或学习重排，应由以上实验决定，而非由论文标题或产品默认值决定。

## 历史追溯：为什么当初会直接比较

下面依据仓库可见历史描述实现意图，不能据此判断开发者当时是否意识到某项风险，也不能把“未找到证明”说成“证明当时完全没考虑”。

1. **2026-03-11，最早可见 graph strategy 并不混排。**在 [`853f3f5` 的 `activation_v1.py` 第 81–115 行](https://github.com/matrixorigin/memoria/blob/853f3f5714d914c877f315976569a7ada96e16c3/memoria/core/memory/strategy/activation_v1.py#L81)，graph 只要有结果就返回；否则走内部 vector fallback。因而，直接跨路比较并不是第一版 graph 策略就有的问题。同期 [graph scorer 第 123–148 行](https://github.com/matrixorigin/memoria/blob/853f3f5714d914c877f315976569a7ada96e16c3/memoria/core/memory/graph/retriever.py#L123) 已采用自己的加权分数及类型乘数，但当时并不需要靠这个总分与 fallback 总分竞争。

2. **2026-03-14，PR #21 明确引入“数量不足则补齐，再混排”。**[`aa50616` 的 `activation_v1.py` 第 124–161 行](https://github.com/matrixorigin/memoria/blob/aa50616d7d31277f0b610e27abd656a84ec58fba/memoria/core/memory/strategy/activation_v1.py#L124) 将策略改为 graph 满 K 返回，否则调用 vector 策略补充，并按 `retrieval_score` 降序。第 150–153 行有明确原始注释：

   > Merge: deduplicate, then sort by retrieval_score descending.
   > Graph results have activation-based scores; vector results have
   > vector/keyword scores. Sorting by score lets the best results win
   > regardless of which path produced them.

   这说明“让不同来源结果按分竞争”是有意实现的启发式，而非偶然漏写排序。但注释中的 “best results win” 依赖于分数能够跨路比较的假设，注释本身没有证明该假设。Python 版本先遍历 graph，再遍历 vector，同 ID 保留第一次出现的 graph 结果，并非两路取最大分。

3. **当时考虑过分数数值，但不等于做过跨路校准。**同一提交的 [tabular scorer 第 508–544 行](https://github.com/matrixorigin/memoria/blob/aa50616d7d31277f0b610e27abd656a84ec58fba/memoria/core/memory/tabular/retriever.py#L508) 明确将 BM25 做 `s/(s+1)` 归一化、L2 做 `1/(1+L2)`，然后加权并乘频次 boost。[`test_score_preserves_raw_value` 第 260–283 行](https://github.com/matrixorigin/memoria/blob/aa50616d7d31277f0b610e27abd656a84ec58fba/tests/unit/test_memory_retriever.py#L260) 还明确要求大于 1 的原始分数不能被截断。因此不能声称“当时完全没考虑分数范围”。但检查到的该次测试验证的是分数有值、组件行为、保留原始值、过滤与 fallback 等，没有提供 graph 与 vector 总分可比性的校准或混排质量验证。

4. **2026-03-17，Rust 迁移延续补齐混排策略，并改为重复项取高分。**[`62a7076` / PR #33](https://github.com/matrixorigin/memoria/commit/62a7076b513925b382db07051d021aba5b6060c4) 中，主审代理核对到初版 Rust service 第 322 行满额返回、第 341 行起合并、重复项取高分并混排。该 PR 描述为 “refactor all with rust”，不能据此推断进行了融合效果论证。当前代码仍保留这一策略。

最准确的表述是：**它起源于有明确目的的补齐启发式，使用了未经所查材料证明的跨路分数可比性假设。**已有实现事实足以指出设计风险，但要判断是否实际造成误排、影响哪些查询、改法是否更好，仍需要固定候选池排序对照与端到端评测。仅凭两路公式不同，不足以宣称已证实线上质量故障。
