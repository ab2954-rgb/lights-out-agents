# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [0.1.0] — 2026-08-15
### Added
- LangGraph bank-to-GL close orchestrator with checkpointer and resumable human-in-the-loop interrupt.
- A0–A4 Autonomy Dial: runtime routing (confidence × materiality) and evidence-based promotion/demotion.
- Hash-chained Evidence Ledger with independent verifier and control-ID pulls.
- MCP-style typed ERP tools (GL, bank, idempotent journal posting).
- Hybrid BM25 + dense RAG with reciprocal-rank fusion, reranking, grounded citations and refusal.
- Eval harness (classifier accuracy/incident rate; RAG hit@k, citation precision, refusal accuracy) wired to CI and to autonomy gating.
- Model provider routing with structured outputs and heuristic guardrail cross-check; fully offline default.
