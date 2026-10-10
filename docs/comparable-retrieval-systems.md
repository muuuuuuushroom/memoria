# 图检索与普通检索如何融合：Graphiti、Mem0、LightRAG、Weaviate、Qdrant 对照

核对日期：2026-10-08。本文只记录可访问的一手代码、官方文档与论文；“支持”与“默认”严格区分。以下系统的结果不构成 Memoria 的效果保证。

## Graphiti / Zep

### Graphiti 当前代码（提交 `86f1c941bea7bf53fa45fe4e08c03244b4990eee`）

[官方 `search_config_recipes.py`](https://github.com/getzep/graphiti/blob/86f1c941bea7bf53fa45fe4e08c03244b4990eee/graphiti_core/search/search_config_recipes.py) 提供多种显式 recipe：

- `COMBINED_HYBRID_SEARCH_RRF`：edges、nodes、communities 各自并行跑 BM25 + cosine，再在各自对象类型内 RRF；episodes 只有 BM25。
- `COMBINED_HYBRID_SEARCH_MMR`：edges、nodes、communities 用 BM25 + cosine，再 MMR；`mmr_lambda=1`。
- `COMBINED_HYBRID_SEARCH_CROSS_ENCODER`：edges、nodes 加 BM25 + cosine + BFS，communities 加 BM25 + cosine；各类型用 cross-encoder 重排，但前置处理不完全相同：edges 先 RRF 截至 `2*limit`，episodes 先 RRF 截至 `limit`，nodes/communities 直接对候选名称并集重排。episodes 只有 BM25 候选搜索。
- 另有 edge/node/community 单类的 RRF、MMR、node-distance、episode-mentions 与 cross-encoder recipes。

这表明 Graphiti 将**对象类型通道**（edge/node/episode/community）分开检索与重排，不把 graph 的结构分数直接和一个普通检索总分相加。结果是分类型列表，并非再把这些类型的分数混成一个全局排名。RRF、MMR、图距离、episode mentions 和 cross-encoder 是可替换的 reranker。

### Graphiti 的实际默认入口

[官方 `graphiti.py`](https://github.com/getzep/graphiti/blob/86f1c941bea7bf53fa45fe4e08c03244b4990eee/graphiti_core/graphiti.py#L1652-L1733) 的公开 `Graphiti.search()`：

- 默认 `center_node_uuid is None` 时选择 `EDGE_HYBRID_SEARCH_RRF`；
- 提供中心节点时选择 `EDGE_HYBRID_SEARCH_NODE_DISTANCE`；
- 默认返回限制来自 `DEFAULT_SEARCH_LIMIT=10`（见 [`search_config.py`](https://github.com/getzep/graphiti/blob/86f1c941bea7bf53fa45fe4e08c03244b4990eee/graphiti_core/search/search_config.py#L29-L29)）。

底层 `search_()` 的参数默认是 `COMBINED_HYBRID_SEARCH_CROSS_ENCODER`，因此调用低层 API 时默认行为不同；不能把 recipe 名称误报成所有入口的统一默认值。

当前 `_search()` 是要求传入 config 的兼容委托入口，会调用 `search_()`。默认 cross-encoder client 是 `OpenAIRerankerClient`，可替换；因此不能把配置名 `cross_encoder` 理解成默认必定运行本地 BGE 模型。

[官方 `search.py`](https://github.com/getzep/graphiti/blob/86f1c941bea7bf53fa45fe4e08c03244b4990eee/graphiti_core/search/search.py#L361-L454) 展示了 **edge** cross-encoder 路径：各候选搜索结果先 RRF，最多取 `2*limit` 候选，然后对 query-fact 对重排。这个前置 RRF 不能泛化到所有对象类型；node（约第 599 行）与 community（约第 847 行）分支直接对候选名称并集重排，episode（约第 722 行）先 RRF 截至 `limit`。RRF 实现见 [`search_utils.py`](https://github.com/getzep/graphiti/blob/86f1c941bea7bf53fa45fe4e08c03244b4990eee/graphiti_core/search/search_utils.py#L1775-L1790)：默认函数参数 `rank_const=1`，按零基索引使用 `1/(i+rank_const)`；这与经典 RRF 常见的 `k=60` 不同。Graphiti 在各自对象类型内召回与重排，再返回分类型列表供上下文组装。

### Zep 论文中的架构证据

[Rasmussen 等，*Zep: A Temporal Knowledge Graph Architecture for Agent Memory*，arXiv:2501.13956v1（2025-01-20）](https://arxiv.org/abs/2501.13956) §3.1–3.2 描述三种候选搜索：cosine semantic、Neo4j/Lucene BM25、BFS；分别捕获语义、词法、图上下文。论文将 RRF、MMR、episode-mentions、node-distance、cross-encoder 列为 reranker，并明确说初始检索目标是高召回，reranker 负责提高精度。其实验聚焦检索 20 条 edges 与 entity nodes，并未证明某一种 reranker 对所有任务占优。

对 Memoria 的可转移经验：graph 结构应作为独立候选/重排证据；若需要统一分数，先在同一对象类型或同一候选池内融合，再用共同相关性评分器。Graphiti 的代码是可配置搜索框架，不能直接推断其某个 recipe 一定优于 Memoria 当前策略。

## Mem0：当前与历史实现必须区分

本节依据主审代理核对的官方源码，固定当前提交为 `b7ad69afda6b6ed030347c66d48a13e4de9dec08`。

当前 [Graph Memory 官方说明](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/docs/platform/features/graph-memory.mdx) 已转向共享实体图，以实体命中为 memory 检索加分。当前 [`memory/main.py` 的 `_search_vector_store`](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/memory/main.py#L1642) 先取最多 `max(4K,60)` 的向量候选，再结合关键词分数与实体 boost，交给统一 [`utils/scoring.py`](https://github.com/mem0ai/mem0/blob/b7ad69afda6b6ed030347c66d48a13e4de9dec08/mem0/utils/scoring.py) 排序。

其组合形态是 `min((semantic + normalized_BM25 + entity_boost)/active_max, 1)`，活跃通道的分数上界参与分母；semantic 上界 1、BM25 上界 1、entity boost 上界 0.5。BM25 用随查询长度调整参数的 sigmoid，而非把两个完整检索器的总分取最大。semantic 阈值先于最终组合，且候选源限于向量池：关键词或实体信号不能救回没有进入向量候选池的记忆。当前 `search` 的可选 rerank 默认关闭。

历史 [v1.0.0 的 `memory/main.py`](https://github.com/mem0ai/mem0/blob/v1.0.0/mem0/memory/main.py#L824) 则并行执行向量与外部图查询，以 `results` 和 `relations` 分别返回，可选 rerank 针对向量结果列表。不能用这个历史行为概括当前实现。

[Mem0 论文，2025，arXiv:2504.19413v1](https://arxiv.org/html/2504.19413v1) §2.2 描述实体中心的图遍历和语义 triple 检索。论文不是当前代码上述统一公式的证据，也不应拿整套系统的 benchmark 收益当作该公式的收益。

对 Memoria 的启发：把 graph 信号变成候选的独立特征，让所有候选服从同一评分函数，是另一种合理路线；但还需独立评估召回池是否足够，归一化公式本身也不等于校准概率。

## LightRAG：先对齐成 chunks，再交错去重与可选重排

本节依据主审代理核对的官方源码，固定提交为 `453dce83d6d0354a06e46c8d4029a0895c4e054b`。

当前 [官方 README](https://github.com/HKUDS/LightRAG/blob/453dce83d6d0354a06e46c8d4029a0895c4e054b/README.md) 中，`hybrid` 指 local entities + global relations，`mix` 在此基础上加入 naive 向量文本检索；当前说明推荐并以 mix 为默认模式。这个命名与一些产品把 lexical+dense 叫 hybrid 不同。

[`operate.py` 的 `_merge_all_chunks`](https://github.com/HKUDS/LightRAG/blob/453dce83d6d0354a06e46c8d4029a0895c4e054b/lightrag/operate.py#L5765) 将实体和关系映射到背后原始 chunks，再与 vector chunks 合并：按 `vector[i] → entity[i] → relation[i]` 交错取候选，按 chunk ID 去重。它没有直接比较图检索总分与向量总分。

[`utils.py` 的 `process_chunks_unified`](https://github.com/HKUDS/LightRAG/blob/453dce83d6d0354a06e46c8d4029a0895c4e054b/lightrag/utils.py#L7055) 可对合并后的 chunk 文本使用同一 reranker，然后应用分数阈值、top-K 和 token budget。只有启用并配置模型才会执行 rerank；否则保留候选顺序。实体/关系上下文本身仍另外保留，不能把整个系统简化为只对 chunks 排序。

[原始 LightRAG 论文，arXiv:2410.05779](https://arxiv.org/abs/2410.05779) 初版 2024 年，后续版本 2025 年，描述 local entities/global relationships 双层检索与邻居扩展；它不是当前 2026 年源码中 round-robin 和 reranker 实现的历史证据。

对 Memoria 的启发：若 graph node 与 memory row 不是同一种返回对象，先映射到共同的原始记忆/证据单位，再合并去重；没有可比的分数时，可把交错召回作为廉价基线，再用同一重排器评分。交错配额和 chunk 映射也可能造成信息丢失或偏置，需要独立评估。

## Weaviate

[官方 Hybrid Search 文档](https://docs.weaviate.io/weaviate/concepts/search/hybrid-search)说明 hybrid 并行执行 vector 与 BM25，再融合**归一化分数**。支持两种方法：

- `relativeScoreFusion`：每路最高分映射为 1、最低分映射为 0，中间值按原始相对距离缩放；这是 **v1.24 起默认**。
- `rankedFusion`：只按每路名次，用 `1/(rank+60)` 形式累加；这是 **v1.23 及更早默认**。

文档明确指出 relativeScoreFusion 保留比分数名次更多的信息；同时 alpha 控制 vector 权重，服务器默认 alpha 为 `0.75`（但客户端可能显式发送不同值，因此要检查客户端行为）。这是一种普通 vector/BM25 hybrid 的成熟实现，不是 graph 总分与 lexical 总分的直接比较。

对 Memoria 的启发：若采用列表内 min-max，必须固定候选窗口并处理全相等/单条候选；alpha 需要显式记录。relativeScoreFusion 的产品默认也不能替代 Memoria 自身标注调参。

## Qdrant

[官方 Hybrid Queries 文档](https://qdrant.tech/documentation/concepts/hybrid-queries/)（Query API；hybrid/multi-stage 自 v1.10.0）要求先用 `prefetch` 执行多路子查询，再用主 query 融合；文档提醒 prefetch limit 至少应覆盖主查询 `limit+offset`。

- `rrf`：使用各路名次，默认 `k=2`（Qdrant 使用零基名次，首项贡献 `1/(k+0)`）；默认各路权重 1。RRF 常数可从 v1.16.0 配置；加权 RRF 从 v1.17.0 配置。
- `dbsf`：从每一路返回集计算均值与样本标准差，以 `mu±3sigma` 作为端点，按 `(s-(mu-3sigma))/(6sigma)` 归一后求和；自 v1.11.0。它保留分数幅度，但统计只来自当前 prefetch top-k，异常值会影响结果；全相等或单点时输出 0.5。

Qdrant 文档明确建议：有评估集时用一半查询调权重、另一半验证；没有评估集就保留等权默认，手调权重未必可靠。文档也明确说 DBSF 与加权 RRF 没有普遍赢家，应由评估集选择。

对 Memoria 的启发：必须分开候选 prefetch 窗口和最终 K；RRF 的 `k` 不可照抄别的产品；DBSF 的 query-local 统计可能在短列表上不稳定，graph/hybrid 的候选分布与异常值需单独测量。

## 与 Memoria 的比较结论

| 系统 | 默认/实际融合位置 | graph 结构如何进入排序 | 关键限制 |
| --- | --- | --- | --- |
| Graphiti `Graphiti.search()` | edge 通道默认 BM25+cosine 后 RRF；有中心节点时 node-distance；低层 `search_()` 默认 combined cross-encoder recipe | BFS、中心节点距离、episode mentions、cross-encoder 作为候选/重排证据 | 不同入口默认不同；跨 edge/node/community 不是单一裸分 |
| Weaviate v1.24+ | vector + BM25 归一后 relativeScoreFusion，alpha 默认服务器值 0.75 | 无知识图谱通道 | 仅说明普通 hybrid；min-max 依赖候选窗口 |
| Mem0 当前提交 | 向量候选池上统一 semantic+BM25+entity 特征评分 | 共享实体图命中作为 boost | 向量候选池外的记忆无法由关键词/实体单独救回；不能混用历史版本结论 |
| LightRAG 当前 mix | graph 映射 chunks 与 vector chunks 交错去重，之后可选统一 rerank | local/global 图结果与原始证据映射，另保留实体关系上下文 | rerank 需启用并配置；hybrid 与 mix 含义不同 |
| Qdrant v1.10+ | prefetch 后显式选择 RRF 或 DBSF；DBSF 从 v1.11 起，RRF 默认等权 `k=2` | 所述 hybrid 不是知识图谱检索方案 | DBSF 依赖当前 top-k 分布；权重需验证 |
| Memoria 当前路径 | graph 满 K 可提前返回；不足时与 hybrid 结果按复合 `retrieval_score` 竞争 | graph activation、类型/实体/时效/置信度等已混入 graph 总分 | 所查历史未找到跨路校准证明；graph 与 hybrid 共享部分 lexical/vector 信号 |

因此，最接近 Memoria 的成熟模式不是“直接把 graph 总分和普通总分取 max”，而是：扩大各路候选窗口，保留来源与结构特征，在候选池上用 RRF/归一化融合或共同重排器；对于 graph 证据，再用路径、中心距离、mentions 或 cross-encoder 等结构感知特征做后续排序。是否改善质量仍需固定候选池和端到端两类实验验证。
