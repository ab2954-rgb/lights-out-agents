# Contributing

Thanks for your interest. This repository is a reference implementation; contributions that make it a better teaching artefact or a safer production pattern are welcome.

## Ground rules
- **Determinism first.** Anything that decides whether an agent may act (matching, materiality, idempotency, autonomy gating) must be plain code with tests — never a prompt.
- **Offline CI.** Tests and evals must run without API keys. Provider-specific code goes behind `llm/provider.py` and is optional.
- **Evidence.** New agent actions must append to the Evidence Ledger with the control IDs they evidence.
- **Evals gate features.** If you change classification, retrieval, or the autonomy policy, extend the golden sets and keep `python examples/run_evals.py` green.

## Workflow
```bash
pip install -e ".[dev]"
pre-commit install            # optional, mirrors CI
ruff check src tests examples && pytest -q && python examples/run_evals.py
```
Open a PR against `main` using the template. Small, focused PRs with a test are merged fastest.

## Adding a new Lights-Out function
1. Add typed tools in `tools/` (Pydantic schema, idempotent mutations).
2. Build the graph in `agents/` — reuse `AutonomyPolicy` and `EvidenceLedger`; do not fork them.
3. Add a golden set in `data/` and an eval in `evals/`.
4. Document the decision in `docs/adr/`.
