# Lights-Out Agents

**Agentic AI reference implementation for Lights-Out finance operations** — a working, tested slice of the five-layer stack I use to take enterprise functions from human-operated to autonomous, with the controls a regulated enterprise needs to let agents act.

[![ci](https://github.com/ab2954-rgb/lights-out-agents/actions/workflows/ci.yml/badge.svg)](https://github.com/ab2954-rgb/lights-out-agents/actions)
Python 3.10+ · LangGraph · LangChain · Pydantic · runs fully offline in CI (no API keys required); plug in Claude / GPT-4.x / Cohere with two env vars.

> Companion to [Lights Out Finance](https://lightsoutfinance.net) — autonomous finance for CFOs: the continuous close, self-steering planning, self-evidencing controls.

---

## What's in here

| Module | What it demonstrates | Production analogue |
|---|---|---|
| `agents/close_orchestrator.py` | **LangGraph** bank-to-GL close agent: `fetch → match → classify → decide → [human interrupt] → act → summarise`. Typed state, conditional edges, checkpointer, resumable human-in-the-loop. | Same graph, checkpointer on Postgres, tools on an MCP server, traced in LangSmith/Langfuse |
| `autonomy/dial.py` | **A0–A4 Autonomy Dial**: runtime decision (confidence × materiality → auto / human approval / escalate) and the **ratchet** — levels are earned on eval evidence and demoted on incident. | Per-function autonomy policy governed by model-risk committee (SR 11-7) |
| `ledger/evidence_ledger.py` | **Hash-chained Evidence Ledger**: every agent action, autonomy decision and human intervention is an immutable, control-mapped record; `verify_chain()` is a pure function an auditor can run on the export. | WORM/object-lock store; regulator-facing evidence pulls by control ID |
| `tools/erp_tools.py` | **MCP-style typed tools** for GL, bank and journal posting (Pydantic schemas → JSON schema, idempotent mutations). | Adapters over SAP OData/BAPI, Oracle Fusion, NetSuite SuiteTalk, Workday, published via an MCP server |
| `rag/pipeline.py` | **Enterprise RAG** over finance policies: sentence-aware chunking, **hybrid BM25 + dense** retrieval with reciprocal-rank fusion, reranking, grounded answers with chunk citations and explicit refusal. | Cohere Embed v3 + Rerank v3 (or OpenAI/Voyage), pgvector / Qdrant index |
| `evals/harness.py` | **Eval harness → CI gate**: golden datasets, classifier accuracy/incident rate, RAG hit@k / citation precision / refusal accuracy; thresholds fail the build and **gate autonomy promotion**. | RAGAS / LangSmith datasets, regression gates in GitHub Actions |
| `llm/provider.py` | **Model routing + structured outputs**: cheap model for classification, stronger model for drafting; Pydantic contract via `with_structured_output`; heuristic cross-check as a guardrail; deterministic offline fallback. | Anthropic / OpenAI / Bedrock / Vertex, prompt caching, cost & latency budgets |

## Architecture

```mermaid
flowchart LR
  subgraph L1[Data & Knowledge]
    ERP[(SAP · Oracle · NetSuite · Workday)]
    POL[(Policies / vector store)]
  end
  subgraph L2[Models & Intelligence]
    CLS[Classifier · structured output]
    RAG[Hybrid RAG · rerank]
  end
  subgraph L3[Agentic Orchestration]
    G[LangGraph close agent]
    DIAL{A0–A4 Autonomy Dial}
    HITL[Human interrupt]
  end
  subgraph L4[Integration & Ops]
    MCP[MCP tool server]
    OBS[Tracing · evals · cost]
  end
  subgraph L5[Governance]
    LED[(Evidence Ledger · hash chain)]
    CTRL[SOX · SR 11-7 · DORA · GDPR control map]
  end
  ERP --> MCP --> G
  POL --> RAG --> G
  G --> CLS --> DIAL
  DIAL -- auto --> MCP
  DIAL -- approve --> HITL --> MCP
  G --> LED
  HITL --> LED
  OBS --> DIAL
  LED --> CTRL
```

## Quick start

```bash
pip install -e ".[dev]"
pytest -q                                   # 10 tests, offline
python examples/run_close.py --level A3     # lights-out below materiality; unknowns escalate
python examples/run_close.py --level A1     # pauses on LangGraph interrupt for human approval, then resumes
python examples/run_evals.py                # eval report + CI gate (exit 1 on breach)
```

Turn on a real model (optional):

```bash
export LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=...     # or LLM_PROVIDER=openai OPENAI_API_KEY=...
pip install -e ".[llm]"
```

The classifier then uses `with_structured_output(ExceptionDecision)`; the heuristic stays on as a **guardrail cross-check** — a confident LLM answer that disagrees with a high-confidence heuristic is down-weighted so the autonomy dial routes it to a human.

## What a run looks like

```
$ python examples/run_close.py --level A3
{
  "items": 6,
  "outcomes": {"matched": 3, "posted": 2, "carried_forward": 1},
  "touchless_rate": 1.0,
  "ledger_head": "345f06f9…dea4",
  "autonomy_level": "A3"
}
evidence ledger: 16 entries, verified=True
```

Six reconciling items: two exact matches, one reference-format mismatch, one short payment (bank fee) and one bank charge auto-posted as adjustments, one 47k receipt in transit carried forward. At **A1** the same run pauses on a LangGraph `interrupt` with three items awaiting approval and resumes with the reviewer's decisions — each recorded in the ledger under `SOX-R2R-05` / `DORA-Art9 human oversight`.

## Design principles

1. **Autonomy is earned, not configured.** `AutonomyPolicy.promote()` only moves a function up a level when the eval harness supplies accuracy, sample size and incident-rate evidence; a breach demotes it. The CI gate and the autonomy gate are the same numbers.
2. **Every action is evidence.** Agents don't produce logs; they produce ledger entries mapped to the control they satisfy. Verification is independent of the producing system.
3. **Deterministic where it matters.** Matching, materiality and idempotent posting are code, not prompts. The model classifies and explains; it doesn't decide whether it may act.
4. **Offline-first, provider-agnostic.** The whole stack runs without keys so tests and evals are reproducible; models, embedders, rerankers and vector stores are injectable.

## Roadmap

- MCP server exposing `erp_tools` (stdio + HTTP) and a LangGraph `ToolNode` variant of the graph
- Postgres checkpointer + pgvector index; Cohere Embed/Rerank adapters
- LangSmith / Langfuse tracing hooks and cost-per-item telemetry into the ledger
- Second function: touchless sales-order processing (Order-to-Cash) on the same dial and ledger

## Author

**Adil Bahir** — Partner, Enterprise AI Enablement & CFO Advisory (KPMG, EMEA); DEng (AI/ML), MBA, MFin, CFA, CPA. Founder, [Lights Out Finance](https://lightsoutfinance.net).

MIT License.
