from lights_out.agents.close_orchestrator import CloseOrchestrator
from lights_out.autonomy.dial import AutonomyPolicy, Level
from lights_out.ledger.evidence_ledger import EvidenceLedger, verify_chain
from lights_out.tools import erp_tools


def _orch(level: Level):
    erp_tools.load_fixture(erp_tools.default_fixture())
    return CloseOrchestrator(AutonomyPolicy("bank_recon", level=level), EvidenceLedger())


def test_a3_runs_lights_out_for_low_materiality_and_escalates_unknowns():
    o = _orch(Level.A3)
    state, _ = o.run()
    outcomes = {o_["outcome"] for o_ in state["pairs"]}
    s = state["summary"]
    assert s["items"] == 6
    assert s["outcomes"]["matched"] == 3            # exact, ref-format, PAY
    assert s["outcomes"]["posted"] == 2             # short payment + bank charge -> adjustments
    assert s["outcomes"]["carried_forward"] == 1    # 47k receipt in transit (A3 auto below 100k)
    assert "escalated" not in outcomes
    assert s["touchless_rate"] == 1.0
    assert verify_chain(o.ledger.export()) == (True, None)
    assert len(erp_tools._FIXTURE.posted_journals) == 2


def test_a1_interrupts_for_human_and_resumes_with_decisions():
    o = _orch(Level.A1)
    state, cfg = o.run()
    assert "summary" not in state                    # paused on interrupt
    snap = o.graph.get_state(cfg)
    assert snap.next == ("human_review",)
    pending = snap.tasks[0].interrupts[0].value["pending"]
    idx = [p["index"] for p in pending]
    assert len(idx) == 3                             # 2 adjustments + 1 carry-forward need approval at A1
    decisions = {str(i): "approve" for i in idx}
    decisions[str(idx[0])] = "reject"
    final = o.resume(cfg, decisions)
    s = final["summary"]
    assert s["outcomes"]["rejected"] == 1
    assert s["items"] == 6
    human_entries = [e for e in o.ledger.entries() if e.actor == "human:reviewer"]
    assert len(human_entries) == 3
    assert verify_chain(o.ledger.export()) == (True, None)


def test_posting_is_idempotent():
    erp_tools.load_fixture(erp_tools.default_fixture())
    args = {"je_id": "JE-1", "debit_account": "6150", "credit_account": "1010", "amount": 1.0, "memo": "x"}
    assert erp_tools.post_journal_entry.invoke(args)["status"] == "posted"
    assert erp_tools.post_journal_entry.invoke(args)["status"] == "already_posted"


def test_tool_schemas_advertised():
    names = {t["name"] for t in erp_tools.tool_schemas()}
    assert names == {"get_gl_lines", "get_bank_lines", "post_journal_entry"}
