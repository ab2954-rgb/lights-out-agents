"""Touchless sales-order release at a chosen autonomy level (second Lights-Out function).

    python examples/run_o2c.py --level A3
"""
import argparse
import json

from lights_out.agents.order_release import OrderReleaseOrchestrator
from lights_out.autonomy.dial import AutonomyPolicy, Level
from lights_out.ledger.evidence_ledger import EvidenceLedger, verify_chain
from lights_out.tools import o2c_tools


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="A3", choices=[lv.name for lv in Level])
    args = ap.parse_args()
    o2c_tools.load_fixture(o2c_tools.default_fixture())
    orch = OrderReleaseOrchestrator(AutonomyPolicy("order_release", level=Level[args.level], low_materiality=2_000, high_materiality=20_000), EvidenceLedger())
    state, cfg = orch.run()
    if "summary" not in state:
        pending = orch.graph.get_state(cfg).tasks[0].interrupts[0].value["pending"]
        print(f"[interrupt] {len(pending)} order(s) awaiting credit-controller approval; demo approves them")
        state = orch.resume(cfg, {str(p["index"]): "approve" for p in pending})
    print(json.dumps(state["summary"], indent=2))
    ok, _ = verify_chain(orch.ledger.export())
    print(f"evidence ledger: {len(orch.ledger.entries())} entries, verified={ok}")


if __name__ == "__main__":
    main()
