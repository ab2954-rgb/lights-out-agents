# ADR-0002 — Every agent action is a hash-chained, control-mapped ledger entry

**Status:** accepted · **Date:** 2026-08-15

## Context
Auditors and regulators do not accept application logs as evidence: logs can be edited, and they don't say which control an action satisfies.

## Decision
Agents append immutable entries (actor, action, subject, autonomy level, payload, control IDs) to an append-only ledger. Each entry commits to the previous entry's SHA-256 over canonical JSON. `verify_chain()` is a pure function over the export, runnable by anyone. Entries carry control IDs so evidence can be pulled control-by-control.

## Consequences
- Tampering, deletion or reordering is detectable at the offending index without trusting the producing system.
- Ledger writes are part of the definition of "done" for an agent action (see CONTRIBUTING).
- Production backends must be WORM/object-lock; the in-memory store here is for tests and demos.

## Alternatives considered
Structured logging + SIEM — rejected as insufficient for independent verification. Full blockchain — rejected as unnecessary; a single-writer hash chain with external anchoring (e.g. periodic hash publication) is enough.
