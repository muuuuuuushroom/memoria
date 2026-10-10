# Memoria 小工程量改进清单

日期：2026-09-23。基于本地 v0.5.2 实现与 moi-benchmark 正式报告；以下均为待实施建议。

目标：用局部修复提升检索正确性、接口一致性和发布可信度，不新增依赖或重做架构。工时为熟悉项目的单人粗估，包含针对性测试，不含外部服务等待。

| 顺序 | 改进 | 最小改动 | 验收标准 | 预计 |
|---|---|---|---|---|
| 1 | 修复混合检索分数混用 | 全文独有候选进入合并集合时，将向量分量置零；保留独立全文分数，不调整现有权重 | 一个回归用例覆盖向量独有、全文独有、共同命中；全文分数不再重复计入向量分量 | 0.5–1 天 |
| 2 | 拒绝非法 memory_type | MCP embedded 对显式非法类型返回校验失败，取消静默转为 semantic；缺省值仍保持原契约，并与 remote／REST 对齐 | 同一非法输入在各入口均不写入、不调用 embedding；合法类型及缺省输入仍正常 | 0.5–1 天 |
| 3 | 让全文检索降级可见 | 在 hybrid 吞掉全文错误并继续向量检索的位置记录结构化 warning，注明操作与错误类别，避免记录正文和凭据 | 注入一次全文查询失败：向量结果仍返回，日志能识别降级；正常空结果不告警 | 0.5 天 |
| 4 | 固定数据库测试版本 | 将 CI 的 MatrixOne `latest` 改成已验证的受支持版本或 digest，优先与基准环境对齐 | 现有数据库测试通过；同一提交重跑使用相同数据库镜像 | 0.5 天 |
| 5 | 补齐手动发布测试门禁 | 手动发布也验证所选 tag；只有该 tag 的测试通过才允许构建发布 | 核对自动与手动触发路径：测试失败或跳过均不能发布，测试与构建 checkout 同一 tag | 0.5–1 天 |
| 6 | 统一 benchmark 报告口径 | 在 moi-benchmark 报告中明确区分入库语料与答案文件，集中列出被测 commit＋diff、抽取开关、Top-K、Reader／Judge；保留 QA 与证据召回两类结果 | 读者能直接看出 S cleaned 用于入库、oracle 用于问题／答案，以及 Controlled Track 不测原生抽取；不将竞品公开分数写成严格排名 | 0.5 天 |

建议先做 1–3，再做 4–6；全部约 3–4.5 人日，可独立提交。

## 实施依据

- 分数混用与静默降级：`memoria/crates/memoria-storage/src/store.rs` 的 `search_hybrid_from_scored_scoped`。
- 类型静默转换：`memoria/crates/memoria-mcp/src/tools.rs` 的 `MemoryStore` handler；REST 已拒绝非法类型。
- CI 与发布：`.github/workflows/test.yml`、`.github/workflows/release-rust.yml`。
- 评测口径：`moi-benchmark/memoria/evaluate/memoria-longmemeval-locomo-final-summary.md` 与对应运行 manifest。

MCP 执行错误的 `isError` 修复已有 [PR #258](https://github.com/matrixorigin/memoria/pull/258)，实施前确认其状态并复用，避免重复开发。

本轮不纳入 agent 权限空间、完整 SSE 会话隔离、请求取消、语义去重重构、新 benchmark 接入或检索架构升级；这些需要独立设计与验证。排除只表示不属于小改动，不表示风险或价值较低。
