# RAG 检索训练：可借鉴的方法与实施顺序

核查日期：2026-10-09。以原论文、作者代码和官方训练文档为依据；Memoria 已有 dense、BM25、graph 检索及本地 RRF 融合原型；本文不把原型视为已发布能力。以下工程优先级是建议，不代表已实现或已测得收益。

## 真正训练检索器的工作

- **DPR**：[论文](https://arxiv.org/abs/2004.04906)／[官方训练代码](https://github.com/facebookresearch/DPR)。训练 query/passage 双编码器，以正例对比 batch 内负例和 BM25 hard negatives，最小化负对数似然。开放域 QA 中证明 dense 可优于 BM25，但不能直接外推到中文个人记忆。适合借鉴三元组数据格式和对比损失，不必复制旧模型及原论文算力配置。
- **ANCE**：[论文](https://arxiv.org/abs/2007.00808)／[代码](https://github.com/microsoft/ANCE)。训练目标仍是 dense relevance；核心是从全库 ANN 动态挖掘当前模型误召回的难负例，并异步更新索引。论文指出训练负例与推理候选分布不一致的瓶颈。Memoria 可周期性离线挖掘 dense+BM25+graph 错误候选，先用轮次更新，避免照搬双后台训练任务；文档编码器变化后须重编码和重建向量索引。
- **RocketQA**：[论文](https://arxiv.org/abs/2010.08191)／[代码](https://github.com/PaddlePaddle/RocketQA)。训练双编码器，使用 cross-batch negatives、cross-encoder 过滤假负例和数据增强；改善 MS MARCO/NQ 检索。最值得复用的是“先去噪再训练”：同一事件的另一条正确记忆不能因未标注就当负例。原版 teacher 过滤不应笼统称为联合端到端训练。
- **ColBERT／ColBERTv2**：[v1](https://arxiv.org/abs/2004.12832)、[v2](https://arxiv.org/abs/2112.01488)／[训练与索引代码](https://github.com/stanford-futuredata/ColBERT)。训练 token 级向量，以 MaxSim late interaction 评分；v2 加入去噪教师监督与压缩。细粒度匹配比单向量更有表达力，v2 降低原 late interaction 空间开销，但仍需多向量索引。Memoria 宜将其作为后续替代 dense 的实验，不能当作直接兼容现有单向量库的模型替换。
- **Contriever、E5、BGE**：[Contriever](https://arxiv.org/abs/2112.09118)／[代码](https://github.com/facebookresearch/contriever)、[E5](https://arxiv.org/abs/2212.03533)／[官方模型](https://github.com/microsoft/unilm/tree/master/e5)、[BGE](https://arxiv.org/abs/2309.07597)／[FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding)。三者分别强调无监督对比预训练、弱监督文本对预训练、中文及通用 embedding 训练资源。它们支持迁移起点的选择，不保证预训练即解决业务相关性；E5 官方目录也不能等同于完整预训练复现代码。优先选择适合中文/多语的现成 BGE/E5，再做域内微调。
- **GPL**：[论文](https://arxiv.org/abs/2112.07577)／[完整 pipeline](https://github.com/UKPLab/gpl)。无标注语料→生成 query→挖负例→cross-encoder 标注正负分差→MarginMSE 训练 dense。直接对应 Memoria 缺标注场景；这是训练 retriever，生成 query 是造训练数据。教师与合成问题可能放大偏差，须加入真实对话和人工校验。

## 排序与生成监督

**Cross-encoder reranking** 训练 query-memory 联合相关性打分，不直接改变召回向量。[Sentence Transformers](https://sbert.net/examples/cross_encoder/training/rerankers/README.html) 和 FlagEmbedding 有成熟训练入口。可用二元交叉熵或候选组排序损失，再以 KL／分差蒸馏给 dense。它适合放在现有 RRF 后；候选没召回时，重排无法补救。

**REPLUG LSR／RA-DIT**：[REPLUG §4](https://arxiv.org/html/2301.12652v3)、[RA-DIT §2.4](https://arxiv.org/html/2310.01352v3)／[RA-DIT 官方代码](https://github.com/facebookresearch/RA-DIT)。冻结 LM，用检索文档下正确答案或文本续写的 likelihood 构造教师分布，以 KL 训练检索分布；RA-DIT 的 R-ft 仅更新 query encoder、冻结 context encoder，免于重建文档索引，另有独立 LM-ft 阶段。优点是优化“是否帮助回答”，局限是需可信答案、较昂贵 LM 打分，并可能偏好 LM 已知的答案；原方法需要获得目标序列 likelihood，仅有聊天输出的 API 不足以直接复现；RA-DIT 仓库 Retriever Setup 存在 WIP，不是完整开箱训练系统。

**Learning-to-rank** 可训练 LambdaMART 等模型融合 dense/BM25 分数、图关系、时间和来源特征；[OpenSearch LTR](https://docs.opensearch.org/latest/search-plugins/ltr/index/) 提供特征记录和模型部署。它训练排序器，不训练 embedding；需分级相关性标签，且时间特征不能机械地把旧事实排除。

## 无需训练 retriever 的方法

[HyDE](https://arxiv.org/abs/2212.10496) 用假设文档作为检索输入；[RAG-Fusion](https://github.com/Raudaschl/rag-fusion) 是多 query 与 RRF；[Self-RAG](https://arxiv.org/abs/2310.11511) 训练生成器的反思 token；[CRAG](https://arxiv.org/abs/2401.15884) 训练/使用检索质量评估器并触发纠正流程。均不应归为 dense retriever 微调。[CONQRR](https://arxiv.org/abs/2112.08558) 用检索奖励强化学习训练对话 query rewriter，固定检索器；对指代、省略问题有价值，但需多次检索采样。Memoria 已有 RRF，继续增加固定融合不等于学习检索能力。

## Memoria 建议优先级

1. **先建评测与重排基线**：保留现有融合候选，对原始 query 与 memory 标注相关性和答案支撑；先运行现成 reranker，再决定是否微调。
2. **再训练 dense**：从真实失败 query 出发，构造多正例与难负例；用 BGE/E5 初始化，以对比损失训练，借鉴 ANCE 周期挖掘、RocketQA 去噪。缺标注时补 GPL 合成数据，以 MarginMSE 蒸馏教师分差，不能把该损失与对比训练混为一谈。
3. **最后优化复杂目标**：有可靠答案标签再试 REPLUG/RA-DIT；对话改写用 CONQRR；多向量 ColBERT 和可学习融合单独做成本收益实验。

训练记录至少含 query、对话上下文、memory ID、时间/版本、多个 positive、负例来源、教师分数。重点挖“同名不同人、同主题不同事件、过期版本、关系方向错误”候选；未知相关性不能直接当负例。所有训练/评测候选应用相同的可见性与时间约束。

按用户、会话、事件和时间隔离训练测试，固定 corpus snapshot，防止同事件改写泄漏。先测各路及融合候选 Recall@20/50、重排 nDCG@10/MRR，再测答案支撑率、无答案拒答、时效冲突处理，以及 P95 延迟/索引空间。多跳题还需“全部必要证据召回率”。做 hard negatives、teacher 去噪、重排、蒸馏的逐项消融；论文的英文 QA/网页检索成绩不能直接预测个人记忆收益。
