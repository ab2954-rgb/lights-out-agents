"""Evaluation harness: golden datasets -> metrics -> autonomy gate.

Two suites:
  * ClassifierEval  — exception classification accuracy / per-class confusion; the
                      accuracy feeds AutonomyPolicy.can_promote (A0 -> A4 ratchet).
  * RAGEval         — retrieval hit@k, citation precision, refusal correctness
                      (RAGAS-style metrics, dependency-free so they run in CI).

Both write a JSON report suitable for a CI gate: the pipeline fails the build if a
metric drops below its threshold (see .github/workflows/ci.yml).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from lights_out.autonomy.dial import AutonomyPolicy, Level
from lights_out.llm.provider import ExceptionDecision, heuristic_classify
from lights_out.rag.pipeline import HybridRetriever, answer


# ----------------------------------------------------------------------------- classifier eval
@dataclass
class ClassifierReport:
    accuracy: float
    samples: int
    confusion: dict[str, dict[str, int]]
    incident_rate: float


def eval_classifier(golden: list[dict], classifier: Callable[[Optional[dict], Optional[dict]], ExceptionDecision] = heuristic_classify) -> ClassifierReport:
    correct, incidents = 0, 0
    conf: dict[str, dict[str, int]] = {}
    for ex in golden:
        pred = classifier(ex.get("gl"), ex.get("bank"))
        truth = ex["label"]
        conf.setdefault(truth, {})[pred.exception_class] = conf.setdefault(truth, {}).get(pred.exception_class, 0) + 1
        if pred.exception_class == truth:
            correct += 1
        # an "incident" is a confident wrong answer that would have auto-executed a mutation
        elif pred.confidence >= 0.85 and pred.proposed_action == "post_adjustment":
            incidents += 1
    n = len(golden)
    return ClassifierReport(accuracy=correct / n if n else 0.0, samples=n, confusion=conf,
                            incident_rate=incidents / n if n else 0.0)


def gate_autonomy(policy: AutonomyPolicy, report: ClassifierReport, observed_samples: Optional[int] = None) -> Level:
    """Promote one level if evidence supports it; demote if incident rate breaches current level's ceiling."""
    samples = observed_samples if observed_samples is not None else report.samples
    ceiling = policy.criteria[policy.level].max_incident_rate
    if report.incident_rate > ceiling:
        return policy.demote("incident_rate_breach")
    return policy.promote(accuracy=report.accuracy, samples=samples, incident_rate=report.incident_rate)


# ----------------------------------------------------------------------------- RAG eval
@dataclass
class RAGReport:
    hit_at_k: float
    citation_precision: float
    refusal_accuracy: float
    n: int
    failures: list[dict] = field(default_factory=list)


def eval_rag(golden: list[dict], retriever: HybridRetriever, llm=None, k: int = 4) -> RAGReport:
    hits = cited_ok = cited_total = refusals_ok = refusals_n = 0
    failures = []
    for ex in golden:
        res = answer(ex["question"], retriever, llm=llm, k=k)
        got_ids = [h.chunk.id for h in res["hits"]]
        if ex.get("expect_refusal"):
            refusals_n += 1
            if res["answer"] == "INSUFFICIENT_CONTEXT":
                refusals_ok += 1
            else:
                failures.append({"q": ex["question"], "type": "should_refuse", "answer": res["answer"]})
            continue
        want_doc = ex["expected_doc"]
        if any(i.startswith(want_doc) for i in got_ids[:k]):
            hits += 1
        else:
            failures.append({"q": ex["question"], "type": "miss", "got": got_ids})
        for c in res["citations"]:
            cited_total += 1
            if c.startswith(want_doc):
                cited_ok += 1
    n_q = len([g for g in golden if not g.get("expect_refusal")])
    return RAGReport(hit_at_k=hits / n_q if n_q else 0.0,
                     citation_precision=cited_ok / cited_total if cited_total else 0.0,
                     refusal_accuracy=refusals_ok / refusals_n if refusals_n else 1.0,
                     n=len(golden), failures=failures)


# ----------------------------------------------------------------------------- CI gate
THRESHOLDS = {"classifier.accuracy": 0.90, "rag.hit_at_k": 0.85, "rag.citation_precision": 0.90, "rag.refusal_accuracy": 1.0}


def write_report(path: Path, classifier: ClassifierReport, rag: RAGReport) -> dict:
    metrics = {
        "classifier.accuracy": classifier.accuracy,
        "classifier.incident_rate": classifier.incident_rate,
        "rag.hit_at_k": rag.hit_at_k,
        "rag.citation_precision": rag.citation_precision,
        "rag.refusal_accuracy": rag.refusal_accuracy,
    }
    breaches = {k: (metrics[k], v) for k, v in THRESHOLDS.items() if metrics[k] < v}
    report = {"metrics": metrics, "thresholds": THRESHOLDS, "breaches": breaches, "pass": not breaches,
              "rag_failures": rag.failures, "confusion": classifier.confusion}
    path.write_text(json.dumps(report, indent=2))
    return report
