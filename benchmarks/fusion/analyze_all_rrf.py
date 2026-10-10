#!/usr/bin/env python3
"""Compare four completed frozen LME-S runs; never invoke APIs or mutate runs."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import statistics

ROOT = Path(__file__).resolve().parent
BENCH = ROOT.parents[1].parent / "moi-benchmark/memoria"
RUNS = BENCH / "runs/fusion-lme-bgem3-full500-v2/retrieval"
VARIANTS = {
    "baseline": "baseline-top20-full500-v1",
    "conditional_rrf": "rrf-top20-full500-v1",
    "all_rrf_equal": "all-rrf-equal-top20-full500-v1",
    "all_rrf_hybrid2": "all-rrf-hybrid2-top20-full500-v1",
}
METRICS = ("recall@20", "complete_recall@20", "hit@1", "mrr@20")
EXPECTED_PATHS = {"graph": 40, "graph+vector": 181, "hybrid": 279}
SEED, RESAMPLES = 42, 5000


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_evaluator():
    path = BENCH / "scripts/longmemeval/evaluate_retrieval.py"
    spec = importlib.util.spec_from_file_location("lme_evaluate_retrieval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, {"path": str(path), "sha256": sha(path.read_bytes())}


def load_run(path: Path):
    sources = {}
    loaded = {}
    for name in ("summary.json", "metrics.json", "manifest.json", "execution-provenance.json", "retrieval.jsonl"):
        data = (path / name).read_bytes()
        sources[name] = sha(data)
        loaded[name] = data
    summary = json.loads(loaded["summary.json"])
    metrics = json.loads(loaded["metrics.json"])
    manifest = json.loads(loaded["manifest.json"])
    for key, expected in {"selected_questions": 500, "snapshot_records": 500,
                          "successful_questions": 500, "failed_questions": 0}.items():
        if summary.get(key) != expected:
            raise ValueError(f"{path.name}: incomplete summary gate {key}")
    if metrics.get("stability_gate", {}).get("passed") is not True:
        raise ValueError(f"{path.name}: stability gate failed")
    if manifest.get("top_k") != 20:
        raise ValueError(f"{path.name}: unexpected top_k")
    ids = list(map(str, manifest["selected_question_ids"]))
    if len(ids) != 500 or len(set(ids)) != 500:
        raise ValueError(f"{path.name}: invalid selected IDs")
    latest = {}
    for line in loaded["retrieval.jsonl"].splitlines():
        row = json.loads(line)
        latest[str(row["question_id"])] = row
    if set(latest) != set(ids):
        raise ValueError(f"{path.name}: snapshot IDs differ from selection")
    for qid, row in latest.items():
        if (row.get("status") != "success" or row.get("validation_ok") is not True
                or len(row.get("results", [])) != 20
                or len(row.get("normalized_results", [])) != 20):
            raise ValueError(f"{path.name}: invalid record {qid}")
        if not math.isfinite(float(row.get("client_total_ms", math.nan))):
            raise ValueError(f"{path.name}: invalid latency {qid}")
    # Detect concurrent writes rather than blending an active run with final gates.
    if any(sha((path / name).read_bytes()) != digest for name, digest in sources.items()):
        raise ValueError(f"{path.name}: source changed during read")
    return latest, {"directory": str(path), "file_sha256": sources,
                    "execution_provenance": json.loads(loaded["execution-provenance.json"])}, metrics


def mean_scores(scores, ids):
    return {metric: statistics.fmean(scores[qid][metric] for qid in ids) for metric in METRICS}


def paired(scores, baseline, ids, evaluator, bootstrap=True):
    result = {}
    for metric in METRICS:
        differences = [scores[qid][metric] - baseline[qid][metric] for qid in ids]
        row = {"count": len(ids), "mean_delta": statistics.fmean(differences),
               "improved": sum(value > 1e-12 for value in differences),
               "regressed": sum(value < -1e-12 for value in differences),
               "unchanged": sum(abs(value) <= 1e-12 for value in differences)}
        if bootstrap:
            rng = random.Random(SEED)
            sampled = [statistics.fmean(rng.choices(differences, k=len(ids))) for _ in range(RESAMPLES)]
            row["paired_bootstrap_95_ci"] = [evaluator.percentile(sampled, 0.025),
                                               evaluator.percentile(sampled, 0.975)]
            low, high = row["paired_bootstrap_95_ci"]
            row["ci_assessment"] = "improvement" if low > 0 else "regression" if high < 0 else "includes_zero"
        result[metric] = row
    return result


def hybrid_counterfactual(rows, quality_ids, baseline_scores, weighted_scores, evaluator):
    valid = {}
    for qid, row in rows.items():
        candidates = row.get("explain", {}).get("candidate_scores", [])
        normalized = row.get("normalized_results", [])
        final_ids = [str(item["memory_id"]) for item in row["results"]]
        candidate_ids = [str(item.get("memory_id")) for item in candidates]
        normalized_by_id = {str(item["memory_id"]): item for item in normalized}
        ranks = [item.get("hybrid_rank") for item in candidates]
        if (len(candidates) != 20 or len(set(candidate_ids)) != 20
                or len(set(final_ids)) != 20 or len(normalized_by_id) != 20
                or not all(type(rank) is int for rank in ranks)
                or set(ranks) != set(range(1, 21))
                or set(final_ids) != set(candidate_ids)
                or set(normalized_by_id) != set(final_ids)):
            continue
        reordered = []
        for candidate in sorted(candidates, key=lambda item: item["hybrid_rank"]):
            original = normalized_by_id[str(candidate["memory_id"])]
            reordered.append({**original, "rank": candidate["hybrid_rank"]})
        raw = evaluator.score_record({**row, "normalized_results": reordered})
        valid[qid] = {metric: raw["mrr" if metric == "mrr@20" else metric] for metric in METRICS}
    result = {"source_variant": "all_rrf_hybrid2", "offline": True,
              "method": "Reorder normalized_results by verified hybrid_rank; reuse score_record. No API run or latency inference.",
              "verified_operational_questions": len(valid),
              "verified_quality_questions": sum(qid in valid for qid in quality_ids),
              "selection_math": {"rrf_k": 60, "top_k_per_channel": 20,
                                 "lowest_hybrid_exclusive_score": 2 / 80,
                                 "highest_graph_exclusive_score": 1 / 61,
                                 "consequence": "When hybrid has 20 unique candidates, hybrid2's final set is entirely hybrid; graph can only rerank that set, not supplement recall."},
              "latency_ms": None}
    if len(valid) != 500:
        result["status"] = "full_counterfactual_unavailable"
        result["note"] = "At least one question lacks verified hybrid ranks 1..20 and identical final IDs; no full-dataset counterfactual metrics reconstructed."
        return result
    result.update(status="verified_full500", quality_questions=470, operational_questions=500,
                  metrics=mean_scores(valid, quality_ids),
                  weighted_rerank_vs_counterfactual=paired(weighted_scores, valid, quality_ids, evaluator),
                  counterfactual_vs_baseline=paired(valid, baseline_scores, quality_ids, evaluator))
    return result


def analyze(runs_root: Path):
    evaluator, evaluator_provenance = load_evaluator()
    runs, provenance, published = {}, {}, {}
    for variant, directory in VARIANTS.items():
        runs[variant], provenance[variant], published[variant] = load_run(runs_root / directory)
    baseline = runs["baseline"]
    ids = sorted(baseline)
    quality_ids = [qid for qid in ids if not baseline[qid].get("is_abstention")]
    if len(quality_ids) != 470:
        raise ValueError("Expected 470 non-abstention quality questions")
    routes = Counter(row["explain"]["path"] for row in baseline.values())
    if dict(routes) != EXPECTED_PATHS:
        raise ValueError(f"Unexpected original routing groups: {dict(routes)}")
    scores, overall = {}, {}
    for variant, rows in runs.items():
        if set(rows) != set(ids):
            raise ValueError(f"{variant}: question IDs do not align")
        for qid in ids:
            original, row = baseline[qid], rows[qid]
            if any(row.get(field) != original.get(field) for field in
                   ("question", "question_type", "is_abstention", "answer_session_ids", "user_id")):
                raise ValueError(f"{variant}: aligned query or annotation mismatch {qid}")
            if variant.startswith("all_rrf_"):
                explain = row["explain"]
                expected_weight = 2.0 if variant == "all_rrf_hybrid2" else 1.0
                if (explain.get("fusion_policy") != "all_channels_rrf"
                        or explain.get("channel_weight") != {"graph": 1.0, "hybrid": expected_weight}
                        or not explain.get("graph_attempted") or not explain.get("vector_attempted")):
                    raise ValueError(f"{variant}: experimental policy gate failed {qid}")
        scores[variant] = {}
        for qid, row in rows.items():
            raw = evaluator.score_record(row)
            scores[variant][qid] = {metric: raw["mrr" if metric == "mrr@20" else metric] for metric in METRICS}
        quality = mean_scores(scores[variant], quality_ids)
        for metric, value in quality.items():
            key = "mrr" if metric == "mrr@20" else metric
            if abs(value - published[variant]["evidence_metrics"]["overall_non_abstention"][key]) > 1e-6:
                raise ValueError(f"{variant}: scorer disagrees with published {metric}")
        latency = [float(rows[qid]["client_total_ms"]) for qid in ids]
        overall[variant] = {"quality_questions": 470, "operational_questions": 500, **quality,
                            "latency_ms": {"p50": evaluator.percentile(latency, 0.50),
                                           "p95": evaluator.percentile(latency, 0.95)},
                            "routing_counts": dict(Counter(row["explain"]["path"] for row in rows.values()))}
    comparisons = {variant: paired(scores[variant], scores["baseline"], quality_ids, evaluator)
                   for variant in ("all_rrf_equal", "all_rrf_hybrid2")}
    counterfactual = hybrid_counterfactual(runs["all_rrf_hybrid2"], quality_ids,
                                         scores["baseline"], scores["all_rrf_hybrid2"], evaluator)
    groups = {}
    for route, operational_count in EXPECTED_PATHS.items():
        group_ids = [qid for qid in quality_ids if baseline[qid]["explain"]["path"] == route]
        groups[route] = {"operational_questions": operational_count, "quality_questions": len(group_ids),
                         "metrics": {variant: mean_scores(values, group_ids) for variant, values in scores.items()},
                         "paired_vs_baseline": {variant: paired(scores[variant], scores["baseline"], group_ids,
                                                                  evaluator, bootstrap=False)
                                                for variant in comparisons}}
    return {"dataset": "LongMemEval-S", "status": "complete_gates_passed",
            "quality_scope": "470 non-abstention questions; session evidence retrieval, not answer accuracy",
            "operational_scope": "500 questions including 30 abstention questions",
            "mrr_definition": "Mean reciprocal rank of the first gold session within the first 20 results; zero if absent.",
            "bootstrap": {"method": "paired question resampling of variant-minus-baseline deltas; percentile CI",
                          "seed": SEED, "resamples": RESAMPLES, "confidence": 0.95,
                          "multiple_comparison_correction": False},
            "latency_caveat": "Conditional-RRF queries were cold in the query cache; its latency is not a fair comparison. Both new runs were prewarmed; compare their warm latencies descriptively. Sequential runs are not randomized latency trials.",
            "routing_caveat": "Groups use the baseline route for each aligned question; requesting both channels does not ensure both provide candidates.",
            "evaluator": evaluator_provenance, "source_provenance": provenance,
            "overall": overall, "paired_vs_baseline": comparisons, "baseline_routing_groups": groups,
            "counterfactual_pure_hybrid": counterfactual}


def markdown(result):
    labels = {"baseline": "Baseline", "conditional_rrf": "旧条件 RRF", "all_rrf_equal": "全通道 1:1", "all_rrf_hybrid2": "全通道 1:2"}
    lines = ["# 全通道 RRF：完整 500 题对比", "",
             "质量指标仅含 470 道非拒答题；运行与延迟含全部 500 题。四组均通过 500 成功、0 失败、完整快照及稳定性门槛。指标衡量证据会话检索，不代表最终问答准确率。", "",
             "| 实验 | Recall@20 | Complete recall@20 | Hit@1 | MRR@20 | P50 / P95 ms |",
             "|---|---:|---:|---:|---:|---:|"]
    for variant, row in result["overall"].items():
        quality = " | ".join(f"{row[metric]:.4f}" for metric in METRICS)
        lines.append(f"| {labels[variant]} | {quality} | {row['latency_ms']['p50']:.1f} / {row['latency_ms']['p95']:.1f} |")
    counterfactual = result["counterfactual_pure_hybrid"]
    if counterfactual["status"] == "verified_full500":
        quality = " | ".join(f"{counterfactual['metrics'][metric]:.4f}" for metric in METRICS)
        lines.append(f"| 离线纯 hybrid 反事实 | {quality} | 未另跑 API，无延迟 |")
    lines += ["", "旧条件 RRF 的查询缓存为冷，延迟不能公平对比；新两组均先预热，只在同等暖缓存条件下描述其速度差异。顺序运行没有随机化，不能归因所有延迟变化。MRR 是首个相关会话排名倒数的平均值（前 20 位无命中为 0），不能解释成平均位置。", "",
              "| 相对 Baseline（470 题） | 指标 | 均值变化 pp | 配对 bootstrap 95% CI pp | 改善 / 退步 / 持平题数 |",
              "|---|---|---:|---:|---:|"]
    for variant, metrics in result["paired_vs_baseline"].items():
        for metric, row in metrics.items():
            low, high = row["paired_bootstrap_95_ci"]
            lines.append(f"| {labels[variant]} | {metric} | {100*row['mean_delta']:+.2f} | [{100*low:+.2f}, {100*high:+.2f}] | {row['improved']} / {row['regressed']} / {row['unchanged']} |")
    lines += ["", "区间按相同 question_id 配对重采样，seed=42，5000 次；未进行多重比较校正。", "",
              "| Baseline 原路径（总题 / 质量题） | 实验 | Recall@20 | Complete recall@20 | Hit@1 | MRR@20 |",
              "|---|---|---:|---:|---:|---:|"]
    for route, group in result["baseline_routing_groups"].items():
        for variant, row in group["metrics"].items():
            quality = " | ".join(f"{row[metric]:.4f}" for metric in METRICS)
            lines.append(f"| {route} ({group['operational_questions']} / {group['quality_questions']}) | {labels[variant]} | {quality} |")
    lines += ["", "分组固定为 Baseline 的纯 graph 40、融合 181、纯 hybrid 279 题，按 question_id 对齐；不会按新实验路径重新分组。完整分组改善/退步计数、来源哈希与构建来源见同名 JSON。请求两个通道不保证两个通道都有候选。", ""]
    for variant, metrics in result["paired_vs_baseline"].items():
        improved = [metric for metric, row in metrics.items() if row["ci_assessment"] == "improvement"]
        regressed = [metric for metric, row in metrics.items() if row["ci_assessment"] == "regression"]
        uncertain = [metric for metric, row in metrics.items() if row["ci_assessment"] == "includes_zero"]
        lines.append(f"{labels[variant]}相对 Baseline：95% 配对区间支持改善的指标为 {'、'.join(improved) or '无'}；支持退步的指标为 {'、'.join(regressed) or '无'}；区间含零的指标为 {'、'.join(uncertain) or '无'}。这是本数据集的检索证据，不能直接推断其他数据集或最终回答表现。")
        lines.append("")
    lines += ["k=60、每路最多 20 条、graph:hybrid=1:2 时，hybrid 独占第 20 名得分 2/80=0.025，仍高于 graph 独占第 1 名的 1/61≈0.01639。因此 hybrid 满 20 条时最终集合全来自 hybrid，graph 只能重排，不能补召回。", ""]
    if counterfactual["status"] == "verified_full500":
        lines += ["全部 500 题均核验最终 memory_id 集合等于 hybrid 的 20 条，且 hybrid_rank 恰为 1..20。离线纯 hybrid 行按这些 rank 重排 normalized_results，仅计算检索质量，未调用 API，也没有单独延迟。", "",
                  "| 1:2 graph 重排相对离线纯 hybrid（470 题） | 均值变化 pp | 配对 95% CI pp | 改善 / 退步 / 持平 |",
                  "|---|---:|---:|---:|"]
        for metric, row in counterfactual["weighted_rerank_vs_counterfactual"].items():
            low, high = row["paired_bootstrap_95_ci"]
            lines.append(f"| {metric} | {100*row['mean_delta']:+.2f} | [{100*low:+.2f}, {100*high:+.2f}] | {row['improved']} / {row['regressed']} / {row['unchanged']} |")
        lines.append("")
    else:
        lines += [f"仅 {counterfactual['verified_operational_questions']}/500 题满足纯 hybrid 重建条件，停止全量反事实重建；不报告全 500 题反事实质量或延迟。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=RUNS)
    parser.add_argument("--output-prefix", type=Path, default=ROOT / "results/all-rrf-comparison")
    args = parser.parse_args()
    result = analyze(args.runs_root)
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    for suffix, data in ((".json", json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"),
                         (".md", markdown(result))):
        destination = args.output_prefix.with_suffix(suffix)
        temporary = destination.with_suffix(suffix + ".tmp")
        temporary.write_text(data)
        temporary.replace(destination)
    print(json.dumps({"status": result["status"], "output_prefix": str(args.output_prefix)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
