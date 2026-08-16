# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [0.2.0] — 2026-08-16
### Added
- MCP server (`lights_out.mcp_server`, FastMCP/stdio) exposing the ERP tools with ledgered calls and `ledger_export`.
- Second Lights-Out function: touchless sales-order release (`agents/order_release.py`, `tools/o2c_tools.py`) on the shared AutonomyPolicy and EvidenceLedger, with O2C control IDs and tests.
- Checkpointer factory (`checkpointing.py`): MemorySaver default, PostgresSaver via `LIGHTS_OUT_PG_DSN`.
- Optional extras: `[mcp]`, `[postgres]`.
- Two technical papers in `docs/papers/`.

## [0.1.0] — 2026-08-15
### Added
- LangGraph bank-to-GL close orchestrator with checkpointer and resumable human-in-the-loop interrupt.
- A0–A4 Autonomy Dial: runtime routing (confidence × materiality) and evidence-based promotion/demotion.
- Hash-chained Evidence Ledger with independent verifier and control-ID pulls.
- MCP-style typed ERP tools (GL, bank, idempotent journal posting).
- Hybrid BM25 + dense RAG with reciprocal-rank fusion, reranking, grounded citations and refusal.
- Eval harness (classifier accuracy/incident rate; RAG hit@k, citation precision, refusal accuracy) wired to CI and to autonomy gating.
- Model provider routing with structured outputs and heuristic guardrail cross-check; fully offline default.
