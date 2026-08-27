from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..domain.models import PlanItem


class AgentAction(StrEnum):
    AUTO_CLASSIFY = "auto_classify"
    PROPOSE_FOR_REVIEW = "propose_for_review"
    HOLD_FOR_REVIEW = "hold_for_review"


@dataclass(frozen=True)
class AgentDecision:
    action: AgentAction
    reason: str
    requires_confirmation: bool


class DocumentAgentBrain:
    """Décide quoi faire après observation, sans exécuter d’action destructive."""

    def decide(self, item: PlanItem) -> AgentDecision:
        if item.classification.needs_review or item.confidence < 45:
            return AgentDecision(
                AgentAction.HOLD_FOR_REVIEW,
                "Confiance insuffisante ou signaux contradictoires : aucune action automatique.",
                True,
            )
        if item.confidence < 80:
            return AgentDecision(
                AgentAction.PROPOSE_FOR_REVIEW,
                "Proposition plausible, mais une validation humaine est recommandée.",
                True,
            )
        return AgentDecision(
            AgentAction.AUTO_CLASSIFY,
            "Signaux convergents et confiance élevée : classement automatique autorisable.",
            False,
        )
