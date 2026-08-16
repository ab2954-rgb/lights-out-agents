from lights_out.agents.order_release import OrderReleaseOrchestrator
from lights_out.autonomy.dial import AutonomyPolicy, Level
from lights_out.ledger.evidence_ledger import EvidenceLedger, verify_chain
from lights_out.tools import o2c_tools


def _orch(level: Level):
    o2c_tools.load_fixture(o2c_tools.default_fixture())
    return OrderReleaseOrchestrator(AutonomyPolicy("order_release", level=level, low_materiality=2_000, high_materiality=20_000), EvidenceLedger())


def test_a3_releases_clean_orders_and_escalates_multi_fail():
    o = _orch(Level.A3)
    state, cfg = o.run()
    # SO-1 (1,000) and SO-5 (480) clean -> auto-released at A3; SO-2 price fail, SO-4 stock fail -> one failed check -> human approval;
    # SO-3 fails credit AND stock -> escalated, never released
    assert "summary" not in state
    pending = o.graph.get_state(cfg).tasks[0].interrupts[0].value["pending"]
    ids = sorted(p["order"]["id"] for p in pending)
    assert ids == ["SO-2", "SO-4"]
    final = o.resume(cfg, {str(p["index"]): ("approve" if p["order"]["id"] == "SO-2" else "reject") for p in pending})
    s = final["summary"]
    assert s["outcomes"] == {"released": 3, "rejected": 1, "escalated": 1}
    assert o2c_tools._FX.released.keys() == {"SO-1", "SO-5", "SO-2"}
    assert verify_chain(o.ledger.export()) == (True, None)
    human = [e for e in o.ledger.entries() if e.actor == "human:credit-controller"]
    assert len(human) == 2 and all("SOX-O2C-04 credit release" in e.controls for e in human)


def test_a1_requires_human_for_everything_mutating():
    o = _orch(Level.A1)
    state, cfg = o.run()
    pending = o.graph.get_state(cfg).tasks[0].interrupts[0].value["pending"]
    assert len(pending) == 4          # 2 clean orders need approval at A1 + 2 single-fail orders; SO-3 escalates


def test_release_is_idempotent():
    o2c_tools.load_fixture(o2c_tools.default_fixture())
    assert o2c_tools.release_order.invoke({"order_id": "SO-1", "reason": "x"})["status"] == "released"
    assert o2c_tools.release_order.invoke({"order_id": "SO-1", "reason": "x"})["status"] == "already_released"
    assert o2c_tools._FX.stock["SKU-A"] == 90
