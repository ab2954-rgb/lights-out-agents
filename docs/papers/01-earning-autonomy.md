# Earning Autonomy: An Evaluation-Gated Ratchet for Agentic Systems in Regulated Enterprises

**Adil Bahir** · Lights Out Finance · August 2026 · Reference implementation: [`lights-out-agents`](https://github.com/adil-bahir/lights-out-agents)

## Abstract

Enterprises do not lack agent demos; they lack a defensible answer to one question from the audit committee: *on what basis is this system allowed to act without a person?* This paper describes the mechanism we use in production to answer it. Autonomy is modelled as a discrete property of a *business function* (not of a model), on a five-level dial from A0 (observe) to A4 (lights-out). Levels are *earned* on measured evidence — accuracy, sample size, and incident rate from an evaluation harness — and *demoted* automatically when the incident rate breaches the ceiling of the current level. The same evaluation numbers gate both the CI pipeline and the autonomy level, so "the tests pass" and "the agent may act alone" become the same fact. At runtime, each action is routed to auto-execution, human approval, or escalation using classifier confidence, materiality, and reversibility, and human approval is enforced by the orchestration graph (an interrupt on a durable checkpoint), never by prompt instruction. We describe the design, the failure modes it was built against, and the code paths in the open-source implementation.

## 1. The problem with "trust the model"

Most agent deployments answer the autonomy question implicitly: a confidence threshold in a prompt, a human "in the loop" whose approval is a formality, or a pilot that never leaves the sandbox. Three failure modes recur.

**Confidence without materiality.** A 99%-confident wrong journal for 10 million is a worse outcome than a 90%-confident wrong bank fee for 40. Any policy that looks only at model confidence will, sooner or later, auto-execute the former.

**Autonomy attached to the model.** If the permission to act is a property of the model or the prompt, swapping the model — a routine engineering event — silently changes what the business has authorised.

**Oversight by instruction.** "Ask a human before posting" in a system prompt is not a control. It is a suggestion the model can misread, forget under long context, or be prompt-injected out of. Auditors are right not to accept it.

## 2. The autonomy dial

We attach an autonomy level to each *function* — bank reconciliation, sales-order release, invoice matching — not to a model:

| Level | Name | Behaviour |
|---|---|---|
| A0 | Observe | agent recommends; humans execute everything |
| A1 | Assist | agent drafts; a human approves every action |
| A2 | Supervise | agent executes low-materiality reversible actions; humans approve the rest |
| A3 | Delegate | agent executes below a high-materiality bar; humans review by exception |
| A4 | Lights-Out | agent executes end-to-end; humans receive evidence, not tasks |

The runtime decision is a pure function:

```
decide(confidence, amount, reversible) -> auto | human_approval | escalate
```

with the level determining the materiality bands and the reversibility requirement (`autonomy/dial.py::AutonomyPolicy.decide`). Confidence below the policy floor always escalates regardless of level; A0 always escalates; A1 always requires approval; A2 permits auto-execution only for low-materiality *reversible* actions; A3 for anything below the high bar; A4 for everything.

## 3. Earning and losing a level

Promotion is gated by evidence produced by the evaluation harness, not by configuration:

| To reach | min accuracy | min samples | max incident rate |
|---|---|---|---|
| A1 | 0.80 | 50 | 10% |
| A2 | 0.90 | 200 | 5% |
| A3 | 0.97 | 1,000 | 1% |
| A4 | 0.995 | 5,000 | 0.2% |

An *incident* is defined narrowly and operationally: a confident wrong answer that would have auto-executed a mutation. Near-misses that routed to a human are not incidents; they are the system working. If the observed incident rate breaches the ceiling of the *current* level, the function is demoted one level automatically and flagged for model-risk review (`evals/harness.py::gate_autonomy`).

The consequence that matters to a risk committee: the numbers that fail the build in CI are the same numbers that decide autonomy. There is no separate "go-live" judgement to be lobbied.

## 4. Enforcing oversight in the graph, not the prompt

The orchestration is a typed LangGraph state machine. When `decide` returns `human_approval` for any item, control passes to a `human_review` node that calls `interrupt(...)` on a durable checkpointer. The run stops. It resumes only with an explicit `Command(resume=decisions)` carrying the reviewer's verdicts, each of which is recorded to the Evidence Ledger under the human's identity and the control it evidences (e.g. `SOX-R2R-05 journal approval`, `DORA-Art9 human oversight`).

Two properties follow. The model cannot skip approval, because approval is a graph edge, not a sentence. And approval survives process restarts, because the checkpoint is durable (Postgres in production; in-memory in tests).

## 5. What the model is — and is not — allowed to decide

Matching, materiality, idempotency, and autonomy gating are code. The model classifies and explains; it does not decide whether it may act. In the reference implementation the classifier returns a Pydantic-typed `ExceptionDecision` (class, confidence, rationale, proposed action) via structured output, and a deterministic heuristic runs alongside it as a guardrail: when a high-confidence heuristic disagrees with the model, the model's confidence is capped so the dial routes the item to a human (`llm/provider.py::classify`). Prompt-injection surface is minimised by construction — the classifier receives structured fields, not free text.

## 6. Results on the reference golden sets

On the repository's deliberately small, readable golden sets, the classifier meets the A2 gate (accuracy 1.00, incident rate 0.00 on 10 items; promotion to A2 requires 200 observed samples in production and is exercised in the tests with `observed_samples=500`), and the RAG harness meets hit@4 = 1.00, citation precision = 1.00, refusal accuracy = 1.00. The numbers are not the point; the mechanism is: extend the golden sets and the gate follows.

## 7. Limitations and open questions

Sample-size thresholds are per function and per environment; ours reflect finance-operations volumes, not a universal law. Incident definition is the load-bearing choice — too narrow and the ratchet is toothless, too broad and no function ever leaves A1. Correlated failures (a model update that degrades many functions at once) are handled today by demotion per function; a portfolio-level circuit breaker is future work. Finally, an autonomy dial does not remove the need for the *evidence* of what happened — that is the subject of the companion paper on hash-chained evidence ledgers.

## References

- Board of Governors of the Federal Reserve System, *SR 11-7: Guidance on Model Risk Management*, 2011.
- Regulation (EU) 2022/2554 (DORA), Art. 9, ICT risk management — human oversight requirements.
- Implementation: `autonomy/dial.py`, `evals/harness.py`, `agents/close_orchestrator.py`, `agents/order_release.py` in `lights-out-agents`; ADR-0001.
