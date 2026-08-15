"""Hash-chained Evidence Ledger.

Every agent action is appended as an immutable, tamper-evident record. Each entry
commits to the previous entry's hash, so any modification anywhere in the chain is
detectable by an independent verifier (auditor / regulator) without trusting the
system that produced it.

Design goals
------------
* Deterministic, canonical JSON serialisation (sorted keys, no whitespace) so
  hashes are reproducible across languages and runtimes.
* Append-only API; verification is a pure function over the exported chain.
* Control mapping: each entry can carry the control IDs it evidences (e.g.
  SOX ITGC-04, SR 11-7 model-monitoring), enabling control-by-control audit pulls.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

GENESIS_HASH = "0" * 64


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LedgerEntry:
    seq: int
    ts: float
    actor: str                     # agent or human id
    action: str                    # e.g. "propose_journal_entry", "post_journal_entry"
    subject: str                   # business object id (recon item, invoice, JE)
    autonomy_level: str            # A0..A4 in force when the action was taken
    payload: dict = field(default_factory=dict)
    controls: tuple[str, ...] = ()   # control IDs evidenced by this action
    prev_hash: str = GENESIS_HASH
    hash: str = ""

    def compute_hash(self) -> str:
        body = asdict(self)
        body.pop("hash")
        return _sha256(_canonical(body))


class EvidenceLedger:
    """In-memory append-only ledger. Swap `_store` for a WORM/object-lock backend in production."""

    def __init__(self) -> None:
        self._store: list[LedgerEntry] = []

    # ---- write path -----------------------------------------------------
    def append(
        self,
        *,
        actor: str,
        action: str,
        subject: str,
        autonomy_level: str,
        payload: Optional[dict] = None,
        controls: Iterable[str] = (),
        ts: Optional[float] = None,
    ) -> LedgerEntry:
        prev = self._store[-1].hash if self._store else GENESIS_HASH
        draft = LedgerEntry(
            seq=len(self._store),
            ts=ts if ts is not None else time.time(),
            actor=actor,
            action=action,
            subject=subject,
            autonomy_level=autonomy_level,
            payload=payload or {},
            controls=tuple(controls),
            prev_hash=prev,
        )
        entry = LedgerEntry(**{**asdict(draft), "controls": draft.controls, "hash": draft.compute_hash()})
        self._store.append(entry)
        return entry

    # ---- read path ------------------------------------------------------
    def entries(self) -> list[LedgerEntry]:
        return list(self._store)

    def head(self) -> str:
        return self._store[-1].hash if self._store else GENESIS_HASH

    def export(self) -> list[dict]:
        return [asdict(e) for e in self._store]

    def by_control(self, control_id: str) -> list[LedgerEntry]:
        return [e for e in self._store if control_id in e.controls]

    def by_subject(self, subject: str) -> list[LedgerEntry]:
        return [e for e in self._store if e.subject == subject]


# ---- independent verifier ----------------------------------------------------
def verify_chain(exported: list[dict]) -> tuple[bool, Optional[int]]:
    """Verify an exported chain. Returns (ok, first_bad_seq).

    Pure function: an auditor can run this over a JSON export without access to
    the producing system.
    """
    prev = GENESIS_HASH
    for i, raw in enumerate(exported):
        entry = LedgerEntry(**{**raw, "controls": tuple(raw.get("controls", ()))})
        if entry.seq != i or entry.prev_hash != prev or entry.compute_hash() != entry.hash:
            return False, i
        prev = entry.hash
    return True, None
