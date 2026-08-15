"""Model provider abstraction.

Selects a chat model from environment configuration and falls back to a
deterministic heuristic when no provider is configured, so the whole graph and
its evals run offline in CI. Model routing (cheap model for classification,
stronger model for narrative/JE memo drafting) is expressed here so it is one
place to change and one place to trace cost.

    LLM_PROVIDER=anthropic  ANTHROPIC_API_KEY=...   -> Claude (langchain-anthropic)
    LLM_PROVIDER=openai     OPENAI_API_KEY=...      -> GPT-4.x (langchain-openai)
    unset                                             -> HeuristicModel (offline)
"""
from __future__ import annotations

import os
from typing import Literal, Optional

from pydantic import BaseModel, Field

ExceptionClass = Literal[
    "matched",
    "reference_format",     # same amount, reference formatted differently
    "short_payment",        # amount differs by a small tolerance (fee / discount)
    "bank_charge",          # bank-only line with no GL entry
    "in_transit",           # GL-only line, no bank line yet
    "unknown",
]


class ExceptionDecision(BaseModel):
    """Structured output contract for the classifier (works with with_structured_output)."""
    exception_class: ExceptionClass
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    proposed_action: Literal["match", "post_adjustment", "carry_forward", "escalate"]


def get_chat_model(role: Literal["classify", "draft"] = "classify"):
    """Return a LangChain chat model or None (offline mode)."""
    provider = os.getenv("LLM_PROVIDER", "").lower()
    try:
        if provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
            from langchain_anthropic import ChatAnthropic

            model = os.getenv("ANTHROPIC_MODEL_CLASSIFY", "claude-3-5-haiku-latest") if role == "classify" \
                else os.getenv("ANTHROPIC_MODEL_DRAFT", "claude-sonnet-4-5")
            return ChatAnthropic(model=model, temperature=0)
        if provider == "openai" and os.getenv("OPENAI_API_KEY"):
            from langchain_openai import ChatOpenAI

            model = os.getenv("OPENAI_MODEL_CLASSIFY", "gpt-4.1-mini") if role == "classify" \
                else os.getenv("OPENAI_MODEL_DRAFT", "gpt-4.1")
            return ChatOpenAI(model=model, temperature=0)
    except ImportError:
        return None
    return None


# ----------------------------------------------------------------------------- offline path
def heuristic_classify(gl: Optional[dict], bank: Optional[dict], tolerance: float = 25.0) -> ExceptionDecision:
    """Deterministic classifier used offline and as a guardrail cross-check for the LLM."""
    if gl and bank:
        diff = round(abs(gl["amount"] - bank["amount"]), 2)
        if diff == 0 and gl["ref"] == bank["ref"]:
            return ExceptionDecision(exception_class="matched", confidence=0.99,
                                     rationale="Exact amount and reference match.", proposed_action="match")
        if diff == 0:
            return ExceptionDecision(exception_class="reference_format", confidence=0.95,
                                     rationale=f"Amounts equal; reference '{bank['ref']}' normalises to '{gl['ref']}'.",
                                     proposed_action="match")
        if diff <= tolerance:
            return ExceptionDecision(exception_class="short_payment", confidence=0.90,
                                     rationale=f"Amount differs by {diff:.2f} within tolerance; likely bank fee/discount.",
                                     proposed_action="post_adjustment")
        return ExceptionDecision(exception_class="unknown", confidence=0.40,
                                 rationale=f"Amount differs by {diff:.2f}, above tolerance.", proposed_action="escalate")
    if bank and not gl:
        if bank["amount"] < 0 and bank["ref"].upper() in {"FEE", "CHG", "CHARGE"}:
            return ExceptionDecision(exception_class="bank_charge", confidence=0.93,
                                     rationale="Negative bank-only line referenced as a fee.", proposed_action="post_adjustment")
        return ExceptionDecision(exception_class="unknown", confidence=0.50,
                                 rationale="Bank-only line without recognisable pattern.", proposed_action="escalate")
    if gl and not bank:
        return ExceptionDecision(exception_class="in_transit", confidence=0.88,
                                 rationale="GL receipt with no bank line yet; carry forward to next statement.",
                                 proposed_action="carry_forward")
    return ExceptionDecision(exception_class="unknown", confidence=0.0, rationale="No data.", proposed_action="escalate")


CLASSIFY_SYSTEM_PROMPT = """You are a reconciliation analyst agent operating under SOX-aligned controls.
Given one GL line and/or one bank line, classify the exception and propose an action.
Be conservative: if unsure, set confidence below 0.7 and propose 'escalate'.
Never invent references or amounts that are not in the input."""


def classify(gl: Optional[dict], bank: Optional[dict]) -> ExceptionDecision:
    """LLM classification with heuristic cross-check; falls back to heuristic offline.

    Guardrail: if the LLM's class disagrees with the heuristic on a high-confidence
    heuristic case, we down-weight confidence so the autonomy dial routes to a human.
    """
    baseline = heuristic_classify(gl, bank)
    model = get_chat_model("classify")
    if model is None:
        return baseline
    structured = model.with_structured_output(ExceptionDecision)
    result: ExceptionDecision = structured.invoke(
        [("system", CLASSIFY_SYSTEM_PROMPT), ("user", f"GL line: {gl}\nBank line: {bank}")]
    )
    if baseline.confidence >= 0.9 and result.exception_class != baseline.exception_class:
        result = result.model_copy(update={"confidence": min(result.confidence, 0.6),
                                           "rationale": result.rationale + " [heuristic disagreement]"})
    return result
