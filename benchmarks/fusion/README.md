# Fusion LongMemEval pilot

Public LongMemEval-S assets are frozen in `pilot-manifest.json` (seed
`20261008`, six categories x five IDs). MaaS BGE-M3 is used through the
ignored `runtime.env` with dimension 1024. The endpoint URL and credentials
are not committed. MatrixOne uses port 16001 and API port 18100.

Reproduction: `python3 benchmarks/fusion/prepare.py`, `docker compose -f benchmarks/fusion/compose.yml up -d`, then `python3 benchmarks/fusion/run_pilot.py ingest`, `baseline`, and `modified`.

Ingest wrote 1,407 memories from 1,410 chunks. Existing safety/upstream
controls rejected `505af2f5`, `7527f7e2`, and `cc539528`; these were not
bypassed. Backfill produced 1,144 graph nodes and zero edges. Both binaries
returned 30/30 Top-20 snapshots with paths graph=4, graph+vector=10,
hybrid=16. Baseline Recall@10/20 was 0.925/0.941667, MRR 0.673889, p95
684.398 ms. Modified p95 was 682.9 ms; ten ranking orders changed. This is
retrieval-only and excludes Reader/Judge. See `results-summary.json` and
`runtime/rankdiff30.json`.

Binary SHA256: baseline `0862fd559f6ce99176812c2e4bf35033f7cee5d34a698aa4fa5002e06fa1628b`; modified `10607d422cc28b85001a3dad4147fb71b0a59812713ab3400f0f5b9422fc2582`.
