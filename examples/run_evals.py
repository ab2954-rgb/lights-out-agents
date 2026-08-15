"""Run classifier + RAG evals, write eval_report.json, exit non-zero on threshold breach (CI gate)."""
import json
import sys
from pathlib import Path

from lights_out.evals.harness import eval_classifier, eval_rag, write_report
from lights_out.rag.pipeline import HybridRetriever, chunk_document

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def main() -> int:
    golden_c = [json.loads(line) for line in (DATA / "golden_classifier.jsonl").read_text().splitlines()]
    golden_r = [json.loads(line) for line in (DATA / "golden_rag.jsonl").read_text().splitlines()]
    chunks = []
    for f in sorted(DATA.glob("policy_*.md")):
        text = f.read_text()
        chunks += chunk_document(text.splitlines()[0].split()[1], text)
    report = write_report(ROOT / "eval_report.json", eval_classifier(golden_c), eval_rag(golden_r, HybridRetriever(chunks)))
    print(json.dumps(report["metrics"], indent=2))
    print("PASS" if report["pass"] else f"FAIL: {report['breaches']}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
