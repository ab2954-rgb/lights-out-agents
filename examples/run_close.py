"""Run the agentic close at a chosen autonomy level and print the summary + ledger head.

    python examples/run_close.py --level A3
    python examples/run_close.py --level A1   # pauses for human review, then auto-approves in demo
"""
import argparse
import json

from lights_out.agents.close_orchestrator import CloseOrchestrator
from lights_out.autonomy.dial import AutonomyPolicy, Level
from lights_out.ledger.evidence_ledger import EvidenceLedger, verify_chain
from lights_out.tools import erp_tools


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="A3", choices=[lv.name for lv in Level])
    args = ap.parse_args()

    erp_tools.load_fixture(erp_tools.default_fixture())
    orch = CloseOrchestrator(AutonomyPolicy("bank_recon", level=Level[args.level]), EvidenceLedger())
    state, cfg = orch.run()
    if "summary" not in state:
        pending = orch.graph.get_state(cfg).tasks[0].interrupts[0].value["pending"]
        print(f"[interrupt] {len(pending)} item(s) awaiting human approval; demo auto-approves them")
        state = orch.resume(cfg, {str(p["index"]): "approve" for p in pending})
    print(json.dumps(state["summary"], indent=2))
    ok, bad = verify_chain(orch.ledger.export())
    print(f"evidence ledger: {len(orch.ledger.entries())} entries, verified={ok}")


if __name__ == "__main__":
    main()
