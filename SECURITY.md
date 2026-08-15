# Security Policy

This project ships no credentials and makes no network calls unless `LLM_PROVIDER` is set. Please report vulnerabilities privately via GitHub's **Report a vulnerability** (Security tab) rather than a public issue. Expect an acknowledgement within 72 hours.

Design notes relevant to security reviews:
- Agent actions are recorded in a hash-chained ledger (`ledger/evidence_ledger.py`); `verify_chain()` detects edits, deletions and reordering.
- Mutating tools are idempotent (`post_journal_entry` keyed on `je_id`).
- Human approval is enforced by the graph (`interrupt`) and the autonomy policy, not by the model.
- Prompt-injection surface: the classifier only receives structured GL/bank fields, never free-text documents; RAG generation is grounded to retrieved chunks and must cite or refuse.
