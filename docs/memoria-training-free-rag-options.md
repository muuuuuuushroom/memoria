# Memoria：无需自行训练的 RAG 优化选项

核查日期：2026-10-09。以下依据原论文摘要、作者代码或官方说明；“无需训练”指使用现成 LLM/embedding，不代表没有离线索引、推理或维护成本。论文数据集收益不能直接外推到个人记忆。

| 方法与原始来源 | 机制及无需训练的实现 | Memoria 场景与限制 |
|---|---|---|
| [HyDE](https://arxiv.org/abs/2212.10496) | LLM 为 query 生成假设文档，现成 encoder 编码该文档，再召回真实语料。保留原 query 检索，将假设文档检索作为额外候选路。 | 适合用户措辞与记忆表述差异大、模糊主题检索。个人经历、人名和日期容易被模型编造，生成内容只能用于检索，不能作为记忆证据；优先低召回时触发。 |
| [RAPTOR](https://arxiv.org/abs/2401.18059)／[作者代码](https://github.com/parthsarthi03/raptor) | 对文本递归 embedding、聚类、摘要，建立多层树；同时检索原文与不同抽象层级的摘要。现成模型即可完成离线构建。 | 适合“最近几个月项目如何变化”等跨会话总结。短原子记忆不一定需要深树；摘要可能遗漏否定、时间和冲突，必须关联原文，新增/删除后更新受影响摘要。 |
| [LightRAG](https://arxiv.org/abs/2410.05779)／[作者代码](https://github.com/HKUDS/LightRAG) | LLM 抽取实体和关系，图结构结合向量索引；分别检索具体实体和高层主题/关系，再合并证据。 | 适合“某人参与哪些项目、这些项目有何关联”。Memoria 已有图，应先借鉴双层 query 与证据组织，避免直接替换全栈。实体合并错误、抽取幻觉和索引维护会影响效果；当前仓库功能也不等同于原论文版本。 |
| [HippoRAG 2](https://arxiv.org/abs/2502.14802)／[作者代码](https://github.com/OSU-NLP-Group/HippoRAG) | 正确论文为 *From RAG to Memory*，以 Personalized PageRank 联想传播，强化 passage 与图的整合，并在线使用 LLM。用现成模型建图和选择检索线索即可。 | 最适合多跳、跨事件关联；可先在已有图上试种子检索与传播，而非重建系统。图边缺失或错误会传播噪声；论文的 non-parametric continual learning 指外部知识持续更新，不是微调模型。 |
| [LongLLMLingua](https://arxiv.org/abs/2310.06839)／[作者代码](https://github.com/microsoft/LLMLingua) | 在召回后对长上下文做压缩和信息布局，使用现成小模型识别应保留的内容；官方包提供 `PromptCompressor`，无需自行训练。 | 适合相关候选已召回但上下文超预算、信息分散的场景。它不补救召回失败；日期、数值、否定、来源 ID 应保护，原文保留供引用。不要把它与需蒸馏训练的 LLMLingua-2 方法混淆。 |
| [Anthropic Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) | 离线用完整文档/会话生成约 50–100 token 的 chunk 专属上下文，附加到 chunk 后建立 embedding 与 BM25 索引，再可接现成 reranker。 | 最适合脱离上下文的“他、那个项目、上周”等记忆。优先补人物、项目、事件日期与来源会话。上下文必须源于当时可见原文；附加字段可能错误或污染词频，保留 raw memory 并区分生成解释与证据。官方结果衡量 retrieval failure，不等于答案正确率。 |

## 建议实施顺序

1. **先修召回预算并建立 reranker 基线**：各路先取大于最终 K 的候选，合并去重后重排，再截断到 K。当前代码检索路径仍会在 graph 足够 K 时提前返回，不能把本地 RRF 原型当作已全面上线融合；小样本、零图边结果也不能证明多跳收益。
2. **先试 Contextual Retrieval，再按失败类型加功能**：上下文丢失补会话解释；语义措辞不匹配试 HyDE；已有召回但长上下文丢信息试 LongLLMLingua。每次只增加一种方法，独立统计额外调用和延迟。
3. **结构化需求明确后再试图与层级索引**：多跳关联优先 HippoRAG 2；实体与主题检索借鉴 LightRAG；跨月/跨项目总结试 RAPTOR。所有派生节点保留原 memory ID、时间和删除关联，避免旧事实被摘要或图继续引用。

按模糊检索、指代、多跳、总结、时间冲突分组评估。分别测候选 Recall@20、最终 nDCG/MRR、多跳全部证据召回率、答案支撑与引用正确率，以及 P95 延迟、索引成本；固定 corpus 与模型，报告逐 query 的收益和退化，而非只给平均分。
