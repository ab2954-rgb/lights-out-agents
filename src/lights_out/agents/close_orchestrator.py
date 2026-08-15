"""Agentic bank-to-GL close orchestrator (LangGraph).

Graph
-----
    fetch -> match -> classify -> decide --(auto)--------> act -> ledger -> END
                                       \\--(human_approval)--> [interrupt] -> act ...
                                        \\--(escalate)-------> escalate -> ledger -> END

* State is a TypedDict; every node is a pure function of state -> partial state.
* `decide` consults the A0–A4 AutonomyPolicy per exception (confidence x materiality).
* Human approval is a LangGraph interrupt on a checkpointer, so a reviewer can
  approve/reject asynchronously and the run resumes exactly where it stopped.
* Every action, decision and human intervention is appended to the Evidence Ledger
  with the control IDs it evidences (SOX ITGC / SR 11-7 / DORA mapping).
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from lights_out.autonomy.dial import AutonomyPolicy
from lights_out.ledger.evidence_ledger import EvidenceLedger
from lights_out.llm.provider import ExceptionDecision, classify
from lights_out.tools import erp_tools

CONTROLS = {
    "match": ("SOX-R2R-03 bank reconciliation", "SR11-7 model-output-monitoring"),
    "post": ("SOX-R2R-05 journal approval", "SOX-ITGC-04 change/authorisation"),
    "human": ("SOX-R2R-05 journal approval", "DORA-Art9 human oversight"),
    "escalate": ("SOX-R2R-03 bank reconciliation",),
}


def _norm_ref(ref: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", ref.upper())


class Pair(TypedDict, total=False):
    gl: Optional[dict]
    bank: Optional[dict]
    decision: Optional[dict]        # ExceptionDecision.model_dump()
    route: Optional[str]            # auto | human_approval | escalate
    outcome: Optional[str]          # matched | posted | carried_forward | escalated | rejected


def _merge_pairs(a: list[Pair], b: list[Pair]) -> list[Pair]:
    return b if b else a


class CloseState(TypedDict, total=False):
    gl_account: str
    bank_account: str
    gl_lines: list[dict]
    bank_lines: list[dict]
    pairs: Annotated[list[Pair], _merge_pairs]
    summary: dict


class CloseOrchestrator:
    def __init__(self, policy: AutonomyPolicy, ledger: EvidenceLedger, actor: str = "agent:recon-01") -> None:
        self.policy = policy
        self.ledger = ledger
        self.actor = actor
        self.graph = self._build()

    # ------------------------------------------------------------------ nodes
    def fetch(self, state: CloseState) -> CloseState:
        gl = erp_tools.get_gl_lines.invoke({"account": state["gl_account"]})
        bank = erp_tools.get_bank_lines.invoke({"account": state["bank_account"]})
        self.ledger.append(actor=self.actor, action="fetch_source_data", subject=state["gl_account"],
                           autonomy_level=self.policy.level.name,
                           payload={"gl_count": len(gl), "bank_count": len(bank)}, controls=CONTROLS["match"])
        return {"gl_lines": gl, "bank_lines": bank}

    def match(self, state: CloseState) -> CloseState:
        """Deterministic candidate pairing on normalised reference, then amount."""
        bank_by_ref = {_norm_ref(b["ref"]): b for b in state["bank_lines"]}
        used: set[str] = set()
        pairs: list[Pair] = []
        for g in state["gl_lines"]:
            b = bank_by_ref.get(_norm_ref(g["ref"]))
            if b is None:  # fall back to unique amount match
                cands = [x for x in state["bank_lines"] if x["id"] not in used and abs(x["amount"] - g["amount"]) <= 25]
                b = cands[0] if len(cands) == 1 else None
            if b:
                used.add(b["id"])
            pairs.append({"gl": g, "bank": b})
        for b in state["bank_lines"]:
            if b["id"] not in used:
                pairs.append({"gl": None, "bank": b})
        return {"pairs": pairs}

    def classify_node(self, state: CloseState) -> CloseState:
        out: list[Pair] = []
        for p in state["pairs"]:
            d: ExceptionDecision = classify(p.get("gl"), p.get("bank"))
            out.append({**p, "decision": d.model_dump()})
        return {"pairs": out}

    def decide(self, state: CloseState) -> CloseState:
        out: list[Pair] = []
        for p in state["pairs"]:
            d = p["decision"]
            amount = abs((p.get("gl") or p.get("bank") or {}).get("amount", 0.0))
            if d["proposed_action"] == "escalate":
                route = "escalate"
            elif d["proposed_action"] == "match":
                route = "auto" if d["confidence"] >= self.policy.min_confidence else "human_approval"
            else:  # post_adjustment / carry_forward mutate or defer -> consult dial
                route = self.policy.decide(confidence=d["confidence"], amount=amount, is_reversible=True)
            self.ledger.append(actor=self.actor, action="autonomy_decision", subject=self._subject(p),
                               autonomy_level=self.policy.level.name,
                               payload={"route": route, "confidence": d["confidence"], "amount": amount,
                                        "class": d["exception_class"]}, controls=CONTROLS["match"])
            out.append({**p, "route": route})
        return {"pairs": out}

    def route_after_decide(self, state: CloseState) -> Literal["human_review", "act"]:
        return "human_review" if any(p["route"] == "human_approval" for p in state["pairs"]) else "act"

    def human_review(self, state: CloseState) -> CloseState:
        """Interrupt: surface items needing approval; resume with {pair_index: 'approve'|'reject'}."""
        pending = [i for i, p in enumerate(state["pairs"]) if p["route"] == "human_approval"]
        decisions: dict = interrupt({"pending": [{"index": i, **state["pairs"][i]} for i in pending]})
        out = list(state["pairs"])
        for i in pending:
            verdict = str(decisions.get(str(i), decisions.get(i, "reject"))).lower()
            self.ledger.append(actor="human:reviewer", action=f"human_{verdict}", subject=self._subject(out[i]),
                               autonomy_level=self.policy.level.name, payload={"index": i}, controls=CONTROLS["human"])
            out[i] = {**out[i], "route": "auto" if verdict == "approve" else "rejected"}
        return {"pairs": out}

    def act(self, state: CloseState) -> CloseState:
        out: list[Pair] = []
        for p in state["pairs"]:
            d, route = p["decision"], p["route"]
            if route == "rejected":
                out.append({**p, "outcome": "rejected"})
                continue
            if route == "escalate":
                self.ledger.append(actor=self.actor, action="escalate_to_human", subject=self._subject(p),
                                   autonomy_level=self.policy.level.name, payload=d, controls=CONTROLS["escalate"])
                out.append({**p, "outcome": "escalated"})
                continue
            action = d["proposed_action"]
            if action == "match":
                outcome = "matched"
            elif action == "carry_forward":
                outcome = "carried_forward"
            else:  # post_adjustment
                gl, bank = p.get("gl"), p.get("bank")
                amount = round(abs((gl["amount"] if gl else 0) - (bank["amount"] if bank else 0)), 2)
                res = erp_tools.post_journal_entry.invoke({
                    "je_id": f"JE-{self._subject(p)}",
                    "debit_account": "6150-BankCharges", "credit_account": "1010-Cash",
                    "amount": amount, "memo": d["rationale"],
                    "source_refs": [x["id"] for x in (gl, bank) if x],
                })
                self.ledger.append(actor=self.actor, action="post_journal_entry", subject=self._subject(p),
                                   autonomy_level=self.policy.level.name, payload=res, controls=CONTROLS["post"])
                outcome = "posted"
            self.ledger.append(actor=self.actor, action=f"outcome_{outcome}", subject=self._subject(p),
                               autonomy_level=self.policy.level.name, payload={"class": d["exception_class"]},
                               controls=CONTROLS["match"])
            out.append({**p, "outcome": outcome})
        return {"pairs": out}

    def summarise(self, state: CloseState) -> CloseState:
        counts: dict[str, int] = {}
        for p in state["pairs"]:
            counts[p["outcome"]] = counts.get(p["outcome"], 0) + 1
        total = len(state["pairs"])
        touchless = counts.get("matched", 0) + counts.get("posted", 0) + counts.get("carried_forward", 0)
        summary = {"items": total, "outcomes": counts, "touchless_rate": round(touchless / total, 3) if total else 0.0,
                   "ledger_head": self.ledger.head(), "autonomy_level": self.policy.level.name}
        self.ledger.append(actor=self.actor, action="close_summary", subject=state["gl_account"],
                           autonomy_level=self.policy.level.name, payload=summary, controls=CONTROLS["match"])
        return {"summary": summary}

    # ------------------------------------------------------------------ graph
    def _build(self):
        g = StateGraph(CloseState)
        g.add_node("fetch", self.fetch)
        g.add_node("match", self.match)
        g.add_node("classify", self.classify_node)
        g.add_node("decide", self.decide)
        g.add_node("human_review", self.human_review)
        g.add_node("act", self.act)
        g.add_node("summarise", self.summarise)
        g.add_edge(START, "fetch")
        g.add_edge("fetch", "match")
        g.add_edge("match", "classify")
        g.add_edge("classify", "decide")
        g.add_conditional_edges("decide", self.route_after_decide, {"human_review": "human_review", "act": "act"})
        g.add_edge("human_review", "act")
        g.add_edge("act", "summarise")
        g.add_edge("summarise", END)
        return g.compile(checkpointer=MemorySaver())

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _subject(p: Pair) -> str:
        gl, bank = p.get("gl"), p.get("bank")
        return "+".join(x["id"] for x in (gl, bank) if x)

    def run(self, gl_account: str = "1010-Cash", bank_account: str = "MAIN-USD", thread_id: str = "close-1"):
        cfg = {"configurable": {"thread_id": thread_id}}
        return self.graph.invoke({"gl_account": gl_account, "bank_account": bank_account, "pairs": []}, cfg), cfg

    def resume(self, cfg: dict, decisions: dict):
        return self.graph.invoke(Command(resume=decisions), cfg)
