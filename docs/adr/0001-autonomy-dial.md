# ADR-0001 — Autonomy is a property of a function, earned on evidence

**Status:** accepted · **Date:** 2026-08-15

## Context
Enterprises will not let an agent post journals because a demo looked good. Model-risk (SR 11-7) and operational-resilience (DORA) regimes require documented, evidence-backed control over what automated systems may do, and a way to reduce that scope when they misbehave.

## Decision
Represent autonomy as five discrete levels (A0 observe → A4 lights-out) attached to a *function* (e.g. bank reconciliation), not to a model. The runtime decision (`AutonomyPolicy.decide`) combines classifier confidence, materiality and reversibility into `auto | human_approval | escalate`. Promotion requires accuracy, sample-size and incident-rate evidence produced by the eval harness; an incident-rate breach demotes automatically.

## Consequences
- The CI eval gate and the autonomy gate use the same numbers, so "it passed evals" and "it may act alone" are the same fact.
- Human oversight is enforced by the graph (`interrupt`), not by prompt instructions.
- Adding a function means adding a golden set before it can leave A1.

## Alternatives considered
Confidence thresholds only (no materiality) — rejected: a 99%-confident wrong 10M journal is worse than a 90%-confident wrong 40 bank fee. Per-model autonomy — rejected: swapping the model shouldn't silently change what the business allows.
