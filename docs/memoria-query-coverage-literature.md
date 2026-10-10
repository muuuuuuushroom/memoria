# 查询覆盖与歧义检索：两篇 NAACL 2025 主会论文核查

核查日期：2026-10-09。已读取 ACL Anthology 元数据与正式全文 PDF，以下页码为论文印刷页码。两篇均发表于 NAACL 2025 主会 Volume 1: Long Papers；不是 Findings 或 workshop。研究范围是给 Memoria 的“上下文双视图 → BM25/dense → RRF → 预训练 Cross-Encoder”增加无需参数训练的机制；本文工程方案均为建议，不代表当前已实现。

## 1. Do RAG Systems Cover What Matters? Evaluating and Optimizing Responses with Sub-Question Coverage

来源：[官方记录](https://aclanthology.org/2025.naacl-long.301/)／[正式全文](https://aclanthology.org/2025.naacl-long.301.pdf)。Kaige Xie 等，2025，pp. 5836–5849。

**问题与机制。** 研究对象是复杂、开放式、非事实短答问题：检索结果可能相关，却没覆盖必要方面。§3.1（pp. 5839–5840）先提示 GPT-4 生成子问题，再单独分类为 core、background、follow-up，避免所有扩展同等重要。core 是回答主问题所必需；background 辅助理解；follow-up 不属于当前必答范围。§3.2 用 GPT-4 判断某个文本能否回答子问题，并要求指出支撑 span，分别评价 retrieval coverage 与 answer coverage。由此可区分“根本没召回”和“召回了但回答未利用”。

**无需训练的边界。** 实验用提示与现成模型：§5（pp. 5843–5844）以 LlamaIndex VectorStoreIndex、OpenAI text-embedding-ada-002、top-K=10 构建 RAG；没有训练新的 query rewriter、embedding 或 reranker。§6 提到未来可将 coverage 用作训练奖励，仅为未来方向，不能倒推该方法需要训练。

**最相关实验。** §5 比较四种增强：只加入 core 定义、直接附加 core 子问题、检索增强、逐子问题回答再合成。最佳方法是 **Retrieval Augmentation**：原 query 与每个 core 子问题分别召回，合并候选，按 core 覆盖重排，取最终 top-K，再回答原 query；优于成本更高的逐子问题生成再汇总。Table 4 对 baseline 的 pairwise win rate 为 73.25%，摘要约写为 74%；这是 GPT-4 对长答案的偏好胜率，不是 Recall 增幅或事实准确率提升。论文没有将该覆盖重排明确实现为“预训练 Cross-Encoder + RRF”，不能声称验证了 Memoria 的具体配置。

**Memoria 可借鉴。** 在复杂汇总问题上生成少量 core 检索问题，例如“今年项目推进如何”拆成目标、里程碑、阻碍、决策等用户实际要求；保留原 query。每个子问题走同一 BM25/dense 双视图召回，再按 memory ID 合并，保留命中子问题与原始来源。RRF 和 Cross-Encoder 后增加 coverage 检查，避免最终 K 个高分候选都回答同一方面。给欠覆盖的 core 单独补检索或保留证据名额。限制子问题数量及总候选预算是工程调整，论文原评测提示生成约 20 个全类型子问题，不建议对所有私人记忆查询照搬。

**局限。** §5 只用 200 个手选 Researchy Questions，候选语料由商业回答引擎引用来源汇集，不是完整个人记忆库。§7 指出分解可能漏掉微妙歧义、GPT-4 coverage 与人类不完全一致、core/background 权重因领域而变，以及额外计算影响实时应用。生成子问题只是检索计划，不能视为用户确有该经历的证据。简单事实题不宜强制扩展。

## 2. Diversify-verify-adapt: Efficient and Robust Retrieval-Augmented Ambiguous Question Answering

来源：[官方记录](https://aclanthology.org/2025.naacl-long.56/)／[正式全文](https://aclanthology.org/2025.naacl-long.56.pdf)。Yeonjun In 等，2025，pp. 1212–1233；方法缩写 **DIVA**。

**问题与机制。** DIVA 处理信息不足导致的多种解释，区别于“一个复杂问题分解成多个必要方面”。§3.2（p. 1215）用两次 LLM 调用：先识别 subject/object/predicate/time/location 哪处有歧义及原因，再生成 pseudo-interpretations。先按原 query 获得候选池 C，再在 C 内用各解释选 top-K，取并集；以所有解释的平均 embedding cosine similarity 剪枝到最终 K。论文使用 ColBERT+Bing 获得 Wikipedia 候选，冻结预训练 Sentence-BERT 做后续匹配（§3.2、附录 A.4.1）。这不是逐解释对全库重新搜索，也不是 RRF 或 Cross-Encoder；若 Memoria 改为逐解释全库 BM25/dense，是针对初始池漏召回的工程扩展。

**证据验证与自适应。** §3.3（p. 1216）对每个 pseudo-interpretation，提示 LLM 判断整个候选上下文能否支持回答，输出 Yes/No。全部 Yes 为 Useful，全部 No 为 Useless，其余为 PartialUseful。Useful 和 PartialUseful 都走 RAG：先抽取解释及对应答案，再生成综合回答；只有 Useless 回退 closed-book LLM。原方法 **没有** 因 PartialUseful 自动迭代补检索，也没有训练 routing classifier。附录 A.4.2 明确验证调用数等于解释数；模型读取拼接候选后逐解释验证，而非廉价单次全局阈值判断。

**无需训练的边界。** §4.4 以 GPT-3.5/GPT-4 做 diversification、verification 与 generation，现成 Sentence-BERT 冻结；DIVA 本身是 few-shot/prompt inference pipeline，无参数更新。实验所用预训练检索模型及评估 D-F1 的已训练 RoBERTa 不构成要求用户自行训练。

**Memoria 可借鉴。** 对“上次那个项目是谁负责”“我当时住哪”等出现人物、事件或时间歧义的 query，先利用真实会话上下文做有限解释，保留各解释标签。不能让平均相关性剪枝把只支持某一种正确解释的证据全部删除；建议重排后按解释保留名额并验证覆盖。证据为 PartialUseful 时标记欠覆盖解释并预算内补检索；Useless 时澄清或拒答。后两项是 Memoria 适配，与原 DIVA 的 closed-book 回退不同：通用 LLM 内部知识不能恢复用户未提供的私人事实。

**效果与局限。** 主实验在 ASQA 与 SituatedQA，另有 100 道不歧义 NQ 小实验。Table 1 中 GPT-4 的 DIVA 27.1 秒，比 Vanilla RAG 18.9 秒慢，比 Iterative RAG 53.1 秒快；“高效”主要相对迭代基线，不能宣称低于普通 RAG 成本。附录 Table 4：DIVA 输入 7,873 token、输出 515，Vanilla RAG 为 3,865/426；验证增加显著成本。§Limitations 指出方法针对歧义 query，混合查询需路由，且验证对 LLM 选择敏感。附录 C.1 的 50 个低分失败样本中，22 个涉及解释生成或冻结 retriever 不足，16 个证据良好但回答失败；因此 verifier 并非正确性保证。主表多数单次运行，附录 C.3 另对 GPT-3.5 D-F1 做五次实验的统计检验，不能把所有配置都描述为重复统计验证。

## 决策与小规模验证

优先在现有 pipeline 上实现 **core 子问题召回与覆盖诊断**；DIVA 的两步歧义分析和逐解释证据验证作为按需路径。Cross-Encoder 的相关性分数不能直接证明“全部方面有证据”；两篇给的是互补覆盖目标，而不是替代现有召回或重排算法。

对简单事实、复杂总结、多实体歧义、时间歧义、无答案各建一组 query，保持 corpus、encoder、reranker 和最终 K 固定。比较 baseline、core 扩展、解释扩展、覆盖验证四组：Recall@K、全部 core/解释证据覆盖率、最终答案支撑率与澄清/拒答准确性，同时记录额外 LLM 调用、token 和 P95。覆盖判定要求返回原 memory ID 与原文 span；人工抽查 LLM coverage 判断，单独报告候选池覆盖与最终上下文覆盖，避免重排剪枝损失被平均分掩盖。
