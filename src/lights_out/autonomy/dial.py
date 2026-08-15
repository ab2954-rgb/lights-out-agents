"""A0–A4 Autonomy Dial.

Each enterprise function (or each action type within it) runs at an autonomy level.
Levels are *earned* on proven accuracy from the evaluation harness and can be
*ratcheted down* automatically on incident. The dial answers one question at
runtime: for this action, at this confidence, in this materiality band — may the
agent act alone, or must a human approve first?

    A0  Observe      agent recommends only; human executes everything
    A1  Assist       agent drafts, human approves every action
    A2  Supervise    agent executes low-materiality actions; human approves the rest
    A3  Delegate     agent executes; human reviews by exception (sampled / flagged)
    A4  Lights-Out   agent executes end-to-end; humans get evidence, not tasks
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Literal

Decision = Literal["auto", "human_approval", "escalate"]


class Level(IntEnum):
    A0 = 0
    A1 = 1
    A2 = 2
    A3 = 3
    A4 = 4


@dataclass
class PromotionCriteria:
    """Accuracy evidence required to hold a level. Produced by evals.harness."""
    min_accuracy: float
    min_samples: int
    max_incident_rate: float


DEFAULT_CRITERIA: dict[Level, PromotionCriteria] = {
    Level.A0: PromotionCriteria(0.00, 0, 1.00),
    Level.A1: PromotionCriteria(0.80, 50, 0.10),
    Level.A2: PromotionCriteria(0.90, 200, 0.05),
    Level.A3: PromotionCriteria(0.97, 1000, 0.01),
    Level.A4: PromotionCriteria(0.995, 5000, 0.002),
}


@dataclass
class AutonomyPolicy:
    function: str
    level: Level = Level.A1
    # materiality thresholds (in reporting currency) below which the agent may act alone at A2/A3
    low_materiality: float = 5_000.0
    high_materiality: float = 100_000.0
    min_confidence: float = 0.85
    criteria: dict[Level, PromotionCriteria] = field(default_factory=lambda: dict(DEFAULT_CRITERIA))

    # ---- runtime decision ----------------------------------------------
    def decide(self, *, confidence: float, amount: float, is_reversible: bool = True) -> Decision:
        if confidence < self.min_confidence:
            return "escalate"
        if self.level == Level.A0:
            return "escalate"          # recommend only
        if self.level == Level.A1:
            return "human_approval"
        if self.level == Level.A2:
            return "auto" if amount < self.low_materiality and is_reversible else "human_approval"
        if self.level == Level.A3:
            return "auto" if amount < self.high_materiality else "human_approval"
        return "auto"                   # A4

    # ---- ratchet ---------------------------------------------------------
    def can_promote(self, *, accuracy: float, samples: int, incident_rate: float) -> bool:
        if self.level == Level.A4:
            return False
        c = self.criteria[Level(self.level + 1)]
        return accuracy >= c.min_accuracy and samples >= c.min_samples and incident_rate <= c.max_incident_rate

    def promote(self, **evidence: float) -> Level:
        if self.can_promote(**evidence):
            self.level = Level(self.level + 1)
        return self.level

    def demote(self, reason: str = "incident") -> Level:  # noqa: ARG002 - reason logged by caller
        if self.level > Level.A0:
            self.level = Level(self.level - 1)
        return self.level
