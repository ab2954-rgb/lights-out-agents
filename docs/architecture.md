# Architecture notes

## Graph state machine
State is a `TypedDict`; `pairs` uses a reducer so partial updates from nodes replace the list atomically. Nodes are pure functions of state; side effects (ERP posting, ledger writes) are isolated to `act` and are idempotent. Human review is a `langgraph.types.interrupt` on a checkpointer, so a run can be paused for hours and resumed with `Command(resume=...)` — the pattern used for maker/checker in production.

## Autonomy dial semantics
`decide()` is the only place where "may the agent act?" is answered. Inputs: classifier confidence, materiality (absolute amount), reversibility. Output: `auto | human_approval | escalate`. Levels are properties of a *function*, not of a model. Promotion evidence comes exclusively from `evals.harness` so autonomy cannot be raised without a passing evaluation.

## Evidence ledger
Entries commit to canonical JSON (sorted keys, no whitespace) with SHA-256 over `prev_hash` + body. `verify_chain()` recomputes every hash and checks sequence continuity — a deleted, edited or reordered record fails verification at its index. Control IDs on each entry allow control-by-control extraction for SOX testing and regulator requests.

## RAG
Finance retrieval needs exact tokens (account codes, control IDs, thresholds) *and* semantic recall, hence BM25 ⊕ dense with reciprocal-rank fusion, then reranking. Grounded generation only sees retrieved chunks and must cite chunk IDs; the harness measures citation precision and refusal correctness, which are what auditors ask about.
