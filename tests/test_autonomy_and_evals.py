import json
from pathlib import Path

from lights_out.autonomy.dial import AutonomyPolicy, Level
from lights_out.evals.harness import eval_classifier, eval_rag, gate_autonomy
from lights_out.rag.pipeline import HybridRetriever, chunk_document

DATA = Path(__file__).resolve().parents[1] / "data"


def test_dial_routes_by_confidence_and_materiality():
    p = AutonomyPolicy("bank_recon", level=Level.A2)
    assert p.decide(confidence=0.95, amount=1_000) == "auto"
    assert p.decide(confidence=0.95, amount=50_000) == "human_approval"
    assert p.decide(confidence=0.50, amount=10) == "escalate"
    p.level = Level.A4
    assert p.decide(confidence=0.95, amount=10_000_000) == "auto"
    p.level = Level.A0
    assert p.decide(confidence=0.99, amount=1) == "escalate"


def test_ratchet_requires_evidence():
    p = AutonomyPolicy("bank_recon", level=Level.A1)
    assert p.promote(accuracy=0.99, samples=10, incident_rate=0.0) == Level.A1     # too few samples
    assert p.promote(accuracy=0.99, samples=500, incident_rate=0.0) == Level.A2
    assert p.demote() == Level.A1


def test_classifier_eval_meets_gate():
    golden = [json.loads(line) for line in (DATA / "golden_classifier.jsonl").read_text().splitlines()]
    rep = eval_classifier(golden)
    assert rep.accuracy >= 0.9, rep.confusion
    assert rep.incident_rate == 0.0
    p = AutonomyPolicy("bank_recon", level=Level.A1)
    assert gate_autonomy(p, rep, observed_samples=500) == Level.A2


def _retriever():
    chunks = []
    for f in sorted(DATA.glob("policy_*.md")):
        doc_id = f.read_text().splitlines()[0].split()[1]   # "# POL-1 ..." -> POL-1
        chunks += chunk_document(doc_id, f.read_text())
    return HybridRetriever(chunks)


def test_rag_eval_meets_gate():
    golden = [json.loads(line) for line in (DATA / "golden_rag.jsonl").read_text().splitlines()]
    rep = eval_rag(golden, _retriever())
    assert rep.hit_at_k >= 0.85, rep.failures
    assert rep.citation_precision >= 0.9
    assert rep.refusal_accuracy == 1.0, rep.failures
