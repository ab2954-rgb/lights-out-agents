"""Touchless sales-order release (Order-to-Cash) — second function on the same dial and ledger.

Graph:  fetch → check → decide → [human_review] → act → summarise

`check` is deterministic policy (price vs list, credit headroom, stock) — code, not prompt.
`decide` consults the shared AutonomyPolicy: confidence here is a policy score (1.0 when every
check passes, lower per failed check); materiality is order value. Same A0–A4 semantics,
same interrupt for human approval, same Evidence Ledger with O2C control IDs.

The point of the second function is to show that AutonomyPolicy and EvidenceLedger are reused
unchanged: adding a Lights-Out function is tools + a graph + a golden set, not a new platform.
"""
from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from lights_out.autonomy.dial import AutonomyPolicy
from lights_out.ledger.evidence_ledger import EvidenceLedger
from lights_out.tools import o2c_tools

CONTROLS = {
    "check": ("SOX-O2C-02 order acceptance", "SR11-7 model-output-monitoring"),
    "release": ("SOX-O2C-04 credit release", "SOX-ITGC-04 change/authorisation"),
    "human": ("SOX-O2C-04 credit release", "DORA-Art9 human oversight"),
}
PRICE_TOL = 0.02  # 2% tolerance vs list price


class Item(TypedDict, total=False):
    order: dict
    checks: dict
    score: float
    route: str
    outcome: str


def _merge(a: list[Item], b: list[Item]) -> list[Item]:
    return b if b else a


class O2CState(TypedDict, total=False):
    items: Annotated[list[Item], _merge]
    summary: dict


class OrderReleaseOrchestrator:
    def __init__(self, policy: AutonomyPolicy, ledger: EvidenceLedger, actor: str = "agent:o2c-01") -> None:
        self.policy, self.ledger, self.actor = policy, ledger, actor
        self.graph = self._build()

    def fetch(self, state: O2CState) -> O2CState:
        orders = o2c_tools.get_open_orders.invoke({"status": "open"})
        self.ledger.append(actor=self.actor, action="fetch_open_orders", subject="O2C", autonomy_level=self.policy.level.name,
                           payload={"n": len(orders)}, controls=CONTROLS["check"])
        return {"items": [{"order": o} for o in orders]}

    def check(self, state: O2CState) -> O2CState:
        out = []
        for it in state["items"]:
            o = it["order"]
            sp = o2c_tools.get_stock_and_price.invoke({"sku": o["sku"]})
            cr = o2c_tools.get_credit_exposure.invoke({"customer": o["customer"]})
            value = o["qty"] * o["unit_price"]
            checks = {
                "price_ok": sp["list_price"] is not None and abs(o["unit_price"] - sp["list_price"]) <= PRICE_TOL * sp["list_price"],
                "credit_ok": cr["remaining_credit"] >= value,
                "stock_ok": sp["on_hand"] >= o["qty"],
            }
            score = sum(checks.values()) / len(checks)
            out.append({**it, "checks": checks, "score": score})
        return {"items": out}

    def decide(self, state: O2CState) -> O2CState:
        out = []
        for it in state["items"]:
            value = it["order"]["qty"] * it["order"]["unit_price"]
            if it["score"] < 1.0:
                route = "escalate" if it["score"] < 0.5 else "human_approval"   # one failed check → human; two or more → escalate
            else:
                route = self.policy.decide(confidence=1.0, amount=value, is_reversible=False)
            self.ledger.append(actor=self.actor, action="autonomy_decision", subject=it["order"]["id"], autonomy_level=self.policy.level.name,
                               payload={"route": route, "checks": it["checks"], "value": value}, controls=CONTROLS["check"])
            out.append({**it, "route": route})
        return {"items": out}

    def route_after_decide(self, state: O2CState) -> Literal["human_review", "act"]:
        return "human_review" if any(i["route"] == "human_approval" for i in state["items"]) else "act"

    def human_review(self, state: O2CState) -> O2CState:
        pending = [i for i, it in enumerate(state["items"]) if it["route"] == "human_approval"]
        decisions: dict = interrupt({"pending": [{"index": i, **state["items"][i]} for i in pending]})
        out = list(state["items"])
        for i in pending:
            verdict = str(decisions.get(str(i), decisions.get(i, "reject"))).lower()
            self.ledger.append(actor="human:credit-controller", action=f"human_{verdict}", subject=out[i]["order"]["id"],
                               autonomy_level=self.policy.level.name, payload={"index": i}, controls=CONTROLS["human"])
            out[i] = {**out[i], "route": "auto" if verdict == "approve" else "rejected"}
        return {"items": out}

    def act(self, state: O2CState) -> O2CState:
        out = []
        for it in state["items"]:
            oid = it["order"]["id"]
            if it["route"] == "auto":
                res = o2c_tools.release_order.invoke({"order_id": oid, "reason": "policy checks passed" if it["score"] == 1.0 else "human approved"})
                self.ledger.append(actor=self.actor, action="release_order", subject=oid, autonomy_level=self.policy.level.name,
                                   payload=res, controls=CONTROLS["release"])
                out.append({**it, "outcome": "released"})
            elif it["route"] == "escalate":
                self.ledger.append(actor=self.actor, action="escalate_to_human", subject=oid, autonomy_level=self.policy.level.name,
                                   payload=it["checks"], controls=CONTROLS["check"])
                out.append({**it, "outcome": "escalated"})
            else:
                out.append({**it, "outcome": "rejected"})
        return {"items": out}

    def summarise(self, state: O2CState) -> O2CState:
        counts: dict[str, int] = {}
        for it in state["items"]:
            counts[it["outcome"]] = counts.get(it["outcome"], 0) + 1
        n = len(state["items"])
        summary = {"items": n, "outcomes": counts, "touchless_rate": round(counts.get("released", 0) / n, 3) if n else 0.0,
                   "ledger_head": self.ledger.head(), "autonomy_level": self.policy.level.name}
        self.ledger.append(actor=self.actor, action="o2c_summary", subject="O2C", autonomy_level=self.policy.level.name,
                           payload=summary, controls=CONTROLS["check"])
        return {"summary": summary}

    def _build(self):
        g = StateGraph(O2CState)
        for name, fn in [("fetch", self.fetch), ("check", self.check), ("decide", self.decide),
                         ("human_review", self.human_review), ("act", self.act), ("summarise", self.summarise)]:
            g.add_node(name, fn)
        g.add_edge(START, "fetch")
        g.add_edge("fetch", "check")
        g.add_edge("check", "decide")
        g.add_conditional_edges("decide", self.route_after_decide, {"human_review": "human_review", "act": "act"})
        g.add_edge("human_review", "act")
        g.add_edge("act", "summarise")
        g.add_edge("summarise", END)
        return g.compile(checkpointer=MemorySaver())

    def run(self, thread_id: str = "o2c-1"):
        cfg = {"configurable": {"thread_id": thread_id}}
        return self.graph.invoke({"items": []}, cfg), cfg

    def resume(self, cfg: dict, decisions: dict):
        return self.graph.invoke(Command(resume=decisions), cfg)
