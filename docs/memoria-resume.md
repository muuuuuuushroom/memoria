# Memoria 项目简历描述

> 目标岗位：AI 应用 / Agent 工程。个人职责为 MCP 接口开发与检索 / 召回优化；简历区分已实现并评测的工作、项目整体基准，以及仍处于方案阶段的 evidence-aware retrieval 设计。

## 一句话定位

面向 AI 应用 / Agent 工程岗位，聚焦 Agent 长期记忆的工具调用与证据检索。负责 MCP 工具接口开发，参与混合检索排序修复及多路召回融合；进一步围绕时间约束、多跳问题和证据缺口设计覆盖感知检索方案，推动系统目标从“找相似记忆”扩展到“在预算内返回可追溯、覆盖关键需求的证据集合”。

## 简历摘要

在 Memoria 长期记忆项目中负责 MCP 工具接口开发并参与检索 / 召回优化。已完成的工作包括混合检索评分修复与图检索 / 混合检索 RRF 融合原型；针对历史事实被过滤、复杂问题证据不全和高相似候选重复等问题，进一步形成分阶段的 evidence-aware retrieval 方案：保留原始记忆及来源，以事实增强索引和时间条件召回扩充候选，再进行来源证据扩展、相关性重排与预算内覆盖选择。该方案尚未实现，未产生新的效果数字。项目既有 LongMemEval-S / LoCoMo 成绩是系统级基准，不作为个人改动的因果收益。

## 简历项目卡片

**Memoria｜面向 AI Agent 的长期记忆与证据检索系统**

**项目时间：**【待补：起止时间】　**个人职责：**MCP 接口开发、检索 / 召回算法优化

**技术栈：** Rust、Tokio、Axum、SQLx、MatrixOne、MCP、Embedding

**项目介绍：** Memoria 为 Agent 提供跨会话记忆的保存、更新与检索能力，帮助找回用户偏好、项目事实和历史经验，并基于 MatrixOne 管理记忆数据。本人负责 MCP 工具接口开发并参与检索 / 召回优化：修复向量与全文候选评分语义混用，探索图检索与混合检索的 RRF 名次融合；同时针对检索到的记忆“相似但不完整、过时或缺少来源”的问题，设计从事实增强索引、时间约束混合召回，到来源扩展、重排和证据覆盖选择的检索方案。后者仍是设计方案，未作为已交付能力或已验证收益。项目既有 LongMemEval-S（500 题）和 LoCoMo（1,540 题）GPT-5.4 medium Reader/Judge 端到端准确率分别为 **91.80%（459/500）**、**90.45%（1,393/1,540）**；LongMemEval-S Top-20 平均证据 Recall **97.34%**、Complete Recall **94.04%（442/470）**，检索 p95 **423.3 ms**。上述基准是系统整体结果。

**核心工作与量化结果：**

- **MCP / REST 工具接口：** 负责记忆写入、检索、纠错等 MCP 工具的 schema、调用分发与结果封装，支持本地调用及远程 REST 代理；为检索链路提供 Agent 可调用的统一入口。LoCoMo Top-200 REST 检索评测最终请求成功 **1,540/1,540（100%）**、首次成功率 **98.51%**、客户端 p95 **2,032.4 ms**；这是 REST 检索端指标，不代表 MCP 传输层压测。
- **混合检索与排序：** 参与向量 / 全文并行召回与多信号排序，修复全文独有候选误用向量分、重复加权的问题。LongMemEval-S Top-20 系统基线：证据 Recall **97.34%**、Complete Recall **94.04%（442/470）**、MRR **76.07%**、p95 **423.3 ms**，不将基线成绩归因于单项修复。针对历史事实被时间 / 置信度过滤、复杂查询证据不全及 Top-K 冗余，进一步设计 evidence-aware 检索流程：保留原始记忆与来源，以事实增强索引和时间条件扩充候选，并通过核心子问题与预算内证据覆盖选择组织结果；该流程处于方案阶段，尚未实现或验证。
- **多路召回融合：** 参与图检索与向量 / 全文混合检索的 RRF 融合原型：先分别按通道分数排序并按 `memory_id` 去重；在图召回不足 Top-K 时补充 hybrid 候选，按 `RRF(d)=Σ1/(60+rank_d)` 累加图 / hybrid 名次贡献，合并候选后依融合分排序并截取 Top-K。融合轨迹保留两路 rank 与分数，支持 explain 诊断。LongMemEval-S 30 题试点中 **10/30** 题排序变化，Recall@20 **94.17%**（与 baseline 持平），MRR **0.6711**（baseline **0.6739**）；尚未显示质量提升。

RRF 当前为未提交的本地实现；证据覆盖感知检索为设计方案。评分修复已在当前工作代码中体现。简历表述不将项目的数据库版本管理或整个 REST 服务归为个人开发成果。

### 指标口径与边界

上述 LongMemEval-S 和 LoCoMo 结果采用 moi-benchmark 中的最终受控评测：Memoria `0.4.0`，固定写入的 semantic memories，不经过 `/v1/observe` 原生 LLM 抽取；Reader/Judge 为 GPT-5.4 medium，使用固定的 Mem0 公开 Prompt 作为 Zep 未公开 Prompt 的可审计代理。LongMemEval-S 检索指标在 470 道非 Abstention 题上计算；LoCoMo 只评估 Category 1–4 的 1,540 题，排除 446 道 Category 5 adversarial 题。LoCoMo Top-200 运行还使用了提高 API Top-K 上限、关闭敏感度过滤的本地评测配置。

公开基准数字是项目在指定数据集、版本和评测配置下的系统结果，不是个人优化前后对照，不能表述为由本人贡献单独带来的提升，也不能据此宣称严格胜过 Mem0 或 Zep。REST 成功率 / p95 来自 LoCoMo Top-200 检索端点，不是 MCP 工具传输的独立压测。RRF 数据来自 30 题小样本试点，排序变化不等于排序质量提升；不能将 LongMemEval-S / LoCoMo 正式基准分数归因于 RRF。

## 精简版

**Memoria｜面向 AI Agent 的长期记忆与证据检索系统**

**项目介绍：** 为 Agent 提供跨会话记忆的写入、更新与检索能力。负责 MCP 记忆工具接口开发，参与混合检索排序修复及图检索 / 混合检索的 RRF 融合原型。针对历史证据被过滤、候选提前截断和复杂问题证据不完整，进一步设计分阶段检索优化方案：解耦候选窗口与最终 K，以“原始记忆 + 有来源事实”增强索引，结合显式时间约束、核心子问题召回和预算内证据覆盖选择；该方案尚待实现与评测。

- **MCP / REST 工具接口：** 负责记忆写入、检索、纠错等 MCP 工具 schema 与调用分发，支持本地调用及远程 REST 代理。LoCoMo Top-200 REST 检索评测中，请求最终完成率 **100%（1,540/1,540）**、首次成功率 **98.51%**，客户端 p95 **2,032.4 ms**（REST 端点指标，非 MCP 协议压测）。
- **混合检索与排序：** 参与修复向量 / 全文混合检索的评分语义混用与重复加权问题，避免全文独有候选错误沿用向量分。项目 LongMemEval-S Top-20 系统基准：证据 Recall **97.34%**、Complete Recall **94.04%（442/470）**、MRR **76.07%**、检索 p95 **423.3 ms**；该结果为系统基准，不归因于单项修复。
- **多路召回融合：** 参与图检索与向量 / 全文混合检索的 RRF 原型：两路候选分别排序、按 `memory_id` 去重；图召回不足 Top-K 时补充 hybrid 结果，以 `Σ1/(60+rank)` 汇总两路名次并重排截断，同时记录 graph / hybrid rank 与分数供 explain 追踪。LongMemEval-S 30 题对照中 **10/30** 题排序变化，Recall@20 **94.17%（与基线持平）**，MRR **0.6711**（基线 **0.6739**），尚无可验证的整体质量提升。

以上三项中的项目基准与 REST 指标均为指定评测配置下的系统结果；RRF 为未提交本地原型及小样本结果。简历其他版本如需加入 evidence-aware retrieval，应明确标注为方案设计、尚未实现。

## 面试开场描述

我在 Memoria 中主要负责 MCP 记忆工具接口开发，并参与检索召回优化。一个具体问题是向量和全文召回分数语义不同，全文独有候选会被错误套用向量分并重复加权；我参与修复了这一路径，也参与图检索与混合检索的 RRF 融合原型。基于现有链路的局限，我进一步整理了证据覆盖感知检索方案：保留原始记忆和来源，通过时间条件与核心子问题扩大候选，再做来源扩展、重排和预算内证据覆盖选择。后几项仍在方案阶段。当前项目 LongMemEval-S 系统检索基线 Recall@20 为 97.34%、MRR 为 76.07%，这些是整体结果，不代表上述改动单独带来的提升。

## HR 开场白

**短版：**

> 您好，我关注贵团队的 AI 应用 / Agent 工程岗位。在 Memoria 中，我负责 MCP 记忆工具接口并参与检索召回优化，具体包括混合检索评分修复和图检索 / 混合检索 RRF 融合原型。LongMemEval-S 系统基线 Top-20 证据 Recall 为 97.34%；我也围绕复杂查询证据缺口梳理了覆盖感知检索方案，目前处于设计阶段。希望进一步交流。

**稍完整版本：**

> 您好，我是【姓名 / 身份】，主要关注 AI 应用与 Agent 工程方向。在 Memoria 中，我负责 MCP 记忆工具接口开发，并参与混合检索评分修复及图检索 / 混合检索 RRF 融合原型。基于当前检索链路在历史事实保留和复杂问题证据覆盖上的不足，我进一步整理了时间约束、来源可追溯和预算内覆盖选择的检索方案，目前还在设计阶段。项目 LongMemEval-S / LoCoMo 端到端系统基准分别为 91.80%（459/500）和 90.45%（1,393/1,540）。希望进一步交流。

## 表达核对表

| 原始职责 / 项目事实 | 简历强化表达 | 事实证据 | 个人边界 | 风险 / 待确认 |
| --- | --- | --- | --- | --- |
| MCP 接口开发 | Agent 记忆工具接入与服务化 | [本地 / 远程接入](/Users/muuushroom/gitrepos/memoria/memoria/crates/memoria-mcp/src/server.rs:179)、[工具发现与调用](/Users/muuushroom/gitrepos/memoria/memoria/crates/memoria-mcp/src/server.rs:449) | 已确认负责 MCP 接口；不扩展为整个 REST 后端开发 | 待补本人接口清单及 PR |
| 混合检索评分修复 | 多源召回评分语义修复 | [候选合并](/Users/muuushroom/gitrepos/memoria/memoria/crates/memoria-storage/src/store.rs:126)、[回归测试](/Users/muuushroom/gitrepos/memoria/memoria/crates/memoria-storage/src/store.rs:6635) | 已确认参与该修复；不声称混合检索从零由本人实现 | 待补质量收益对照 |
| 图检索与 hybrid 的 RRF 融合 | 基于名次的多路召回融合原型 | [融合函数](/Users/muuushroom/gitrepos/memoria/memoria/crates/memoria-service/src/service.rs:230)、[融合调用](/Users/muuushroom/gitrepos/memoria/memoria/crates/memoria-service/src/service.rs:1966) | 已确认参与；不声称图检索算法整体由本人实现 | 未提交本地实现，未证明质量提升 |
| LongMemEval-S / LoCoMo 正式评测 | 项目检索与端到端问答指标背书 | [最终汇总](/Users/muuushroom/gitrepos/moi-benchmark/memoria/README.md:11)、[综合报告](/Users/muuushroom/gitrepos/moi-benchmark/memoria/evaluate/memoria-longmemeval-locomo-final-summary.md:1) | 项目系统结果；不归因于个人单独贡献 | 固定 Reader/Judge 与 Controlled Track，LoCoMo 排除 adversarial 类 |

### 代码对应

- MCP 工具 schema 与 `memory_store` / `memory_retrieve` / `memory_search` 调用：`memoria/crates/memoria-mcp/src/tools.rs:196`、`memoria/crates/memoria-mcp/src/tools.rs:408`。
- MCP 协议校验、工具发现 / 调用、stdio 与 SSE `/sse`、`/message` 入口：`memoria/crates/memoria-mcp/src/server.rs:114`、`memoria/crates/memoria-mcp/src/server.rs:179`、`memoria/crates/memoria-mcp/src/server.rs:193`、`memoria/crates/memoria-mcp/src/server.rs:455`。
- 远程 REST 代理、Bearer / 用户 / 工具请求头及响应校验：`memoria/crates/memoria-mcp/src/remote.rs:9`、`memoria/crates/memoria-mcp/src/remote.rs:16`、`memoria/crates/memoria-mcp/src/remote.rs:201`。
- 向量 / 全文并行召回、候选合并、时效 / 置信度 / 反馈排序：`memoria/crates/memoria-storage/src/store.rs:126`、`memoria/crates/memoria-storage/src/store.rs:6274`、`memoria/crates/memoria-storage/src/store.rs:6318`。
- 全文候选不再污染向量分及对应回归测试：`memoria/crates/memoria-storage/src/store.rs:140`、`memoria/crates/memoria-storage/src/store.rs:6635`。
- 基准原始口径：LongMemEval-S 检索见 [检索报告](/Users/muuushroom/gitrepos/moi-benchmark/memoria/runs/longmemeval-s-bge-m3-relative-shift-v1/retrieval/top20-full500-v1/report.md:1)；最终问答结果及配置边界见 [综合报告](/Users/muuushroom/gitrepos/moi-benchmark/memoria/evaluate/memoria-longmemeval-locomo-final-summary.md:1) 和 [Track README](/Users/muuushroom/gitrepos/moi-benchmark/memoria/README.md:11)。
- REST 接口成功率与延迟见 [LoCoMo 检索报告](/Users/muuushroom/gitrepos/moi-benchmark/memoria/evaluate/locomo-memoria-raw-turn-mem0-compatible-result.md:189)；RRF 小样本对照见 `/Users/muuushroom/gitrepos/moi-benchmark/memoria/runs/fusion-lme-maas-bge-m3-v1/{baseline,modified}/report.md` 及 `rerun-{baseline,modified}/report.md`。

协议参数校验、通知处理和工具执行错误分类也有实现依据，但本人是否负责这些具体改动尚未确认，未写入个人成果。MCP 当前接受取消通知，并未实现真正的执行取消。

## 面试准备

- MCP 工具如何发现和调用？协议错误与工具执行失败为什么要分别返回？本地与远程模式如何复用接口契约？
- 全文独有候选为什么会被误计向量分？修复前后哪个评分输入发生变化，如何用最小例子说明排序问题？
- 图检索和混合检索分数为什么不能直接比较？RRF 保留和丢失了哪些信息，为什么需要与归一化加权融合做对照？
- graph 满额提前返回时，hybrid 是否参与？融合优化与召回门控优化有什么区别？
- LongMemEval-S 的检索 Recall 与端到端 QA 准确率分别衡量什么？Recall 的分母为何是 470，而总体 QA 分母为 500？
- LongMemEval-S 的 91.80% 与 LoCoMo 的 90.45% 使用何种 Reader/Judge 协议？LoCoMo 为何排除 Category 5？这些结果能否归因于某一项个人优化？
- 如何固定候选集合比较排序策略，再用 Recall@K、MRR 和延迟评估端到端效果？为何 30 题、零边的 fusion pilot 不足以证明 RRF 或图关系检索收益？

## 待补信息

1. 项目起止时间。
2. 如需进一步匹配岗位，可补充具体 JD。
3. 本人负责的 MCP 工具 / 协议改动清单，以及对应 PR、提交或设计记录。
4. 如需将基准结果写成个人工作产出，补充你在数据准备、评测执行、指标分析中的具体职责；否则按项目结果保留。
5. RRF 原型的后续合并、发布或实际采用情况。
