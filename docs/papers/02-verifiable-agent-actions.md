# Verifiable Agent Actions: A Hash-Chained, Control-Mapped Evidence Ledger for Autonomous Operations

**Adil Bahir** · Lights Out Finance · August 2026 · Reference implementation: [`lights-out-agents`](https://github.com/adil-bahir/lights-out-agents)

## Abstract

When software agents post journals, release orders, or approve payments, the question an auditor asks is not "did the model log it?" but "can I verify, without trusting your system, what happened, in what order, under whose authority, and which control it satisfies?" Application logs cannot answer that: they can be edited, they are unordered across services, and they say nothing about controls. We describe the Evidence Ledger we use in production: an append-only chain in which every agent action, autonomy decision, and human intervention is a canonical-JSON record committing to the SHA-256 of its predecessor, carrying the actor, the autonomy level in force, and the control identifiers the action evidences. Verification is a pure function over the exported chain that any third party can run; tampering, deletion, or reordering fails at the offending index. We show how the ledger is written from the orchestration graph, how control-by-control evidence pulls replace audit sampling, and where the design deliberately stops short of a blockchain.

## 1. Requirements from the audit committee, not the engineering team

Working with internal audit, external auditors, and model-risk functions across financial services, energy, and pharma clients, the requirements for agent evidence converged on five properties:

1. **Immutability with detection** — not "we promise not to edit logs" but "any edit is detectable by you."
2. **Total order** — across agents, humans, and services, one sequence.
3. **Attribution** — agent identity, human identity, and the autonomy level in force at the moment of action.
4. **Control mapping** — each record names the control(s) it evidences, so evidence can be pulled by control rather than reconstructed from timestamps.
5. **Independence** — verification must not require access to, or trust in, the producing system.

## 2. Ledger design

A ledger entry (`ledger/evidence_ledger.py::LedgerEntry`) is:

```
seq, ts, actor, action, subject, autonomy_level, payload, controls[], prev_hash, hash
```

`hash = SHA-256(canonical_json(entry without hash))`, where canonical JSON means sorted keys, no whitespace, UTF-8, and deterministic serialisation of non-JSON types. `prev_hash` is the previous entry's hash; the genesis predecessor is 64 zeros. Entries are appended, never updated. The in-memory store used in tests and demos is swapped for a WORM / object-lock backend in production; the entry format and verifier are unchanged.

### 2.1 Independent verification

```
verify_chain(exported) -> (ok, first_bad_seq)
```

recomputes every hash and checks `seq` continuity and `prev_hash` linkage. It is a pure function over a JSON export; an auditor can run it in a notebook with no credentials to the producing system. The reference tests demonstrate that editing a payload field, deleting a record, or reordering two records each fails at the correct index.

### 2.2 Control mapping

Every write from the orchestration graph names the controls it evidences, e.g.:

- reconciliation match → `SOX-R2R-03 bank reconciliation`, `SR11-7 model-output-monitoring`
- journal posting → `SOX-R2R-05 journal approval`, `SOX-ITGC-04 change/authorisation`
- human approval → `SOX-R2R-05 journal approval`, `DORA-Art9 human oversight`
- sales-order release → `SOX-O2C-04 credit release`

`by_control("SOX-R2R-05")` returns the complete population of evidence for that control. This turns audit sampling into full-population testing and turns "show me how the agent is controlled" into a query.

## 3. Writing the ledger from the graph

The ledger is written at every point where state changes hands: on fetch (what data the agent saw), on each autonomy decision (route, confidence, amount, class), on each human verdict (under the human's identity), on each mutation (with the tool's idempotent result), and on the summary (with the ledger head hash, so the summary itself is anchored). Because the graph is the only path to the tools, and the graph writes the ledger, an action without a ledger entry is not possible in normal operation — and an entry without a corresponding action is detectable because the tool result is part of the payload.

## 4. What this is not

It is not a blockchain and does not need to be. A single-writer hash chain gives tamper evidence; what it does not give by itself is protection against the writer *rewriting the entire chain from genesis*. Production deployments therefore anchor the head hash externally on a schedule (e.g. publishing it to a system the writer cannot modify — a regulator portal, a notarisation service, or simply the auditor's inbox). With periodic anchoring, a full rewrite is detectable at the next anchor. Distributed consensus buys nothing further for a system with one legitimate writer.

It is also not a replacement for access control. The ledger records what happened; the autonomy dial and the graph decide what is allowed to happen. The two are designed together (see the companion paper on earning autonomy).

## 5. Practical consequences observed in delivery

- **Audit fieldwork shifts from sampling to querying.** Populations by control are complete and verifiable; the conversation moves to control design.
- **Incident review is deterministic.** Given a bad outcome, the ledger yields the data seen, the decision taken, the level in force, and the human (if any) who approved — in order.
- **Autonomy promotion becomes defensible.** The evidence for the incident rate that gates A2→A3 is itself ledgered.
- **The control tower is a view over the ledger**, not a separate telemetry system that can disagree with it.

## 6. Limitations

Canonicalisation must be pinned across languages and versions; a change in float formatting or key ordering breaks historical verification unless versioned. Payloads can contain sensitive data; production stores hash-commit large or sensitive payloads and keep the raw content in a governed store keyed by the ledger hash. High-frequency functions need batching or a Merkle-tree variant to keep verification cost linear in the number of batches rather than actions.

## References

- Haber, S. & Stornetta, W. S. (1991). *How to time-stamp a digital document.* Journal of Cryptology.
- PCAOB AS 2201 / SOX §404 control testing; SR 11-7 model risk management; DORA Art. 9.
- Implementation: `ledger/evidence_ledger.py`, `agents/close_orchestrator.py`, `agents/order_release.py`, `mcp_server.py` (ledgered tool calls); ADR-0002; tests `tests/test_ledger.py`.
