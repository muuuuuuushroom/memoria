# Retrieval fusion mini benchmark

Inspection date: 2026-10-08. Retrieval baseline should use upstream commit
`6247235e27bc62898b122473dafae084bea61c80` or a newer explicitly pinned commit.
The local checkout is `9962999`, seven commits behind the inspected upstream.
No benchmark or service startup was performed during this inspection.

## Available Local Assets

The native CLI supports `benchmark --dataset PATH --out REPORT.json`, as well as
`--api-url`, `--token`, and `--validate-only`.

| Dataset | Scenarios | Seeds | Retrieval assertions |
| --- | ---: | ---: | ---: |
| core-v2 | 15 | 67 | 19 |
| graph-entity-v2 | 10 | 44 | 10 |
| large-graph-v2 | 2 | 122 | 12 |

These are handcrafted regression datasets, not independent public benchmarks.
The native scorer matches expected/excluded substrings in returned content.
Changing the order of the same Top-K results does not change its score. It can
detect membership changes, but is insufficient as the primary reranking metric.
Its executor also does not verify completion of governance maturation requests.
The presence of graph-oriented cases does not guarantee the target merge branch
is exercised.

## Public Benchmark Infrastructure

The adjacent repository is `/Users/muuushroom/gitrepos/moi-benchmark`.
Relevant scripts, relative to its `memoria/` directory:

- `scripts/longmemeval/ingest.py`: deterministic session/chunk ingestion;
  supports repeated `--question-id`, `--start-index`, and `--limit`.
- `scripts/longmemeval/retrieve.py`: snapshots results, provenance, explain
  path, timing, and run configuration; supports the same question selectors.
- `scripts/longmemeval/evaluate_retrieval.py`: scores the saved snapshot without
  an LLM reader or judge.
- `scripts/locomo/`: ingestion, retrieval, and reader/judge evaluation scripts.

LongMemEval scoring uses gold `answer_session_ids`. It reports MRR over the first
20 returned chunks, Recall/Hit/CompleteRecall at 1, 5, 10, and 20, plus duplicate
session representation and latency. It measures session evidence coverage,
not exact passage relevance or answer correctness. NDCG is not implemented.
Multiple chunks from a gold session can match even if a particular chunk does
not contain the answer, so inspect changed cases before interpreting gains.

Public sources:

- [LongMemEval code](https://github.com/xiaowu0162/LongMemEval)
- [LongMemEval cleaned datasets](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
- [LoCoMo data](https://github.com/snap-research/locomo/blob/main/data/locomo10.json)

The local adjacent repository retains historical reports and retrieval
snapshots, but its datasets directory lacks `longmemeval_s_cleaned.json`,
`longmemeval_oracle.json`, and `locomo10.json`. Historical manifests refer to
another machine. The historical LongMemEval 500-query and LoCoMo 1,540-query
reports recorded only `hybrid` paths; they do not validate graph/hybrid fusion.

## Recommended Comparison

1. Select and freeze 30 non-abstention LongMemEval-S question IDs: five from
   each of the six official question types, with a fixed selection seed.
   Use the full S histories, including distractors. Oracle-only histories make
   retrieval artificially easy. This is a custom public-data subset, not an
   official leaderboard score.
2. Ingest once using fixed embedding/tokenizer, chunking, confidence, and time
   mapping. Build the graph explicitly and verify completion before taking
   a database snapshot. The current ingestion script does not ensure this.
3. Verify explain paths. The target is partial graph retrieval followed by
   supplementation, currently labeled `graph+vector`. Graph-only and hybrid-only
   cases cannot establish the effect of changing that merge. Report coverage
   on all selected questions; report target-branch outcomes separately without
   claiming they are representative of the whole benchmark.
4. Restore identical database state for baseline and modified services. Fix
   feedback, governance, graph state, time reference, query embeddings, and
   model configuration. Retrieval updates access statistics; access count is
   excluded from current hybrid ranking, but state restoration still protects
   other effects and future changes. Use separate output directories because
   the runner skips already successful questions.
5. Compare paired per-question MRR@20, Recall@5/20, and CompleteRecall@20.
   Report wins/ties/losses and inspect regressions. Measure p50/p95 latency with
   equivalent warmup and several repeats; one quality pass is preliminary
   evidence, while one timing pass is noisy. Thirty questions cannot support a
   strong general improvement claim. Confirm promising changes on a larger
   held-out selection.
6. Also run core-v2 and graph-entity-v2 for regressions. If the public subset
   does not cover partial graph hits, add a separate deterministic merge fixture
   with distractors, overlap, and relevant candidates from both channels. Do
   not mix fixture results into public benchmark averages.

For a fusion-only experiment, replay the same graph/hybrid candidate lists
offline under both formulas before a full service comparison. This isolates
the fusion effect. Candidate traces may require additional instrumentation;
the native CLI report does not preserve them. Gate/candidate-window changes
should be evaluated separately.

## Command Shape

Prerequisites: an isolated Memoria/MatrixOne service, a master key environment
file, `requests` and `sentencepiece`, public data, and the pinned BGE-M3 tokenizer.
The local default ports 8100/6001 were not listening, Docker could not connect
to its configured Colima socket, and no `memoria` executable was on PATH.

The following is a first-30 smoke run, not the recommended stratified selection.
Set the variables to actual local paths and the isolated API before running:

```bash
cd /Users/muuushroom/gitrepos/moi-benchmark/memoria
python3 scripts/longmemeval/ingest.py \
  --dataset "$LME_DATASET" --runtime-env "$BENCH_ENV" \
  --tokenizer-model "$BGE_TOKENIZER" --api-url "$BENCH_API" \
  --user-prefix fusion30- --run-dir runs/fusion30-ingest \
  --limit 30 --workers 1
```

After graph readiness and a database snapshot, run baseline retrieval:

```bash
python3 scripts/longmemeval/retrieve.py \
  --dataset "$LME_DATASET" --runtime-env "$BENCH_ENV" \
  --api-url "$BENCH_API" --user-prefix fusion30- \
  --run-dir runs/fusion30-before --limit 30 --top-k 20 --workers 1
python3 scripts/longmemeval/evaluate_retrieval.py \
  --run-dir runs/fusion30-before
```

Restore the same database snapshot, start the modified service, and repeat the
last two commands using `runs/fusion30-after`. For stratified selection, replace
`--limit 30` in ingestion and both retrieval runs with the identical repeated
`--question-id ID` arguments. Use separate timing-repeat directories as well.

An isolated native regression run, once a CLI is built, is:

```bash
memoria benchmark --api-url "$BENCH_API" --token "$BENCH_TOKEN" \
  --dataset /Users/muuushroom/gitrepos/memoria/benchmarks/datasets/graph-entity-v2.json \
  --out graph-entity-before.json
```

All commands above are prospective; none was executed against a database.
