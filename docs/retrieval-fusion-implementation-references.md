# 融合排序实施参考（固定源码核对）

核对日期：2026-10-08。这里只记录成熟项目的实际源码；没有在 Memoria 上运行或保证质量收益。

## 三个一手实现

### Qdrant

Qdrant `master` 提交 [`016542aa5deb6c66380bb137badf73d54f742bde`](https://github.com/qdrant/qdrant/tree/016542aa5deb6c66380bb137badf73d54f742bde)，源码 [`reciprocal_rank_fusion.rs`](https://github.com/qdrant/qdrant/blob/016542aa5deb6c66380bb137badf73d54f742bde/lib/segment/src/common/reciprocal_rank_fusion.rs)。`DEFAULT_RRF_K=2`；位置是零基，默认贡献为 `1/(position+2)`，输入原始分数完全无关。支持每一路权重，但实现是将位置除以权重的“压缩”，不是简单把整路最终分数乘权。其默认 `k=2` 等价于一基名次公式中的平滑常数 `c=1`。

### Weaviate

Weaviate 提交 [`519a9ba23b390590d12641775dd958c2d80687cc`](https://github.com/weaviate/weaviate/tree/519a9ba23b390590d12641775dd958c2d80687cc) 的 [`usecases/traverser/hybrid/hybrid_fusion.go`](https://github.com/weaviate/weaviate/blob/519a9ba23b390590d12641775dd958c2d80687cc/usecases/traverser/hybrid/hybrid_fusion.go) 实现 `FusionRanked`：每路贡献 `weights[i]/(i+60)`，`i` 零基，因此相当于一基名次的 `c=59`；源码注释仍写着 TODO 将 60 改为可配置。另有 `FusionRelativeScore`，在每路候选内按 min/max 归一后加权。该实现是 vector/BM25 hybrid 的普通候选融合，不能直接证明 graph 总分应同样处理。

### Graphiti

Graphiti 提交 [`86f1c941bea7bf53fa45fe4e08c03244b4990eee`](https://github.com/getzep/graphiti/tree/86f1c941bea7bf53fa45fe4e08c03244b4990eee) 的 [`search_utils.py#L1775`](https://github.com/getzep/graphiti/blob/86f1c941bea7bf53fa45fe4e08c03244b4990eee/graphiti_core/search/search_utils.py#L1775) 实现 `rrf(results, rank_const=1)`：零基位置贡献 `1/(i+1)`，相当于一基名次 `c=0`。它在 edge cross-encoder 前作为候选预排序；不同 node/edge/community 类型分别返回，不能视为全局 graph-vs-hybrid 分数融合。

## Memoria 的保守方案与短列表风险

当前 graph 满 `top_k` 时会提前返回；graph 不足时才与 hybrid 合并。建议先保持这些门控语义，仅替换“partial graph + hybrid”的**候选池内排序**，并保留每个候选的来源、原始分项、名次和最终 fused score。可把经典 RRF 定义为一基名次 `1/(c+rank)`，先做等权 `c=60` 对照；此值来自 Cormack 等 SIGIR 2009 原始论文，不是上述三个项目的共同默认值。

`c=60` 对 Memoria 的短列表影响很大。若 hybrid 有 20 项、graph 只有 19 项，graph 第 19 名和 hybrid 第 20 名的交集候选得分为 `1/79+1/80≈0.02516`，高于只在一路排第 1 的候选 `1/61≈0.01639`。即使 graph/hybrid 各有 20 项，双路第 20 名 `2/80=.025` 也高于单路第 1 名。换言之，大 `c` 会显著偏好双路重叠；这可能是好事，也可能放大 graph 与 hybrid 共享 lexical/vector 信号的重复奖励。必须在固定候选并集上报告 overlap、Recall/NDCG/MRR 与路径分层结果，不能只凭公式选择。

因此建议先做三种**只读对照**：现有 raw-score merge、等权 RRF(`c=60`)、等权 RRF(`c=1` 或项目默认等价值)，候选窗口和返回 K 完全相同。若短列表双路重叠过强，再测较小 `c`、按来源权重，或保留原始 graph 结构特征的统一重排。graph 满额 early-return 的 graph-only 流量应单独统计，不能用 partial-fusion 结果推断其质量。

## 实施边界

- 不把 RRF 分数解释为概率，也不把 Qdrant `k=2`、Weaviate 常数 60、Graphiti `rank_const=1` 互称为同一默认值；零基/一基差异已在上面展开。
- 不把候选未出现的另一路当作“真实零分”而声称复现加权融合论文；那属于截断候选并集实验，需要单独标注。
- 首轮实验固定写入快照与查询集合；分别比较候选池内融合和 graph 满额的端到端门控。记录 latency、候选数、来源重叠、graph-only/partial/hybrid 路径及退化错误。
