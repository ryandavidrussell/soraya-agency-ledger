from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional

from router import GovernanceRoute, SorayaMode, RouterDecision


LEDGER_SCHEMA_VERSION = "soraya_agency_ledger_v0.1"

MODE_SYSTEM_ACTIONS = {
    SorayaMode.CLARIFY: "Returned ambiguity to the user as one smaller choice or clarifying question.",
    SorayaMode.TRIAGE: "Compressed overload into a short priority frame while leaving final priority ownership with the user.",
    SorayaMode.TINY_STEP: "Provided one small starter action to restore motion without taking over the task.",
    SorayaMode.SAFETY: "Paused coaching and redirected toward appropriate human, professional, or policy review.",
}

MODE_NEXT_STEP_SIZE = {
    SorayaMode.CLARIFY: "small",
    SorayaMode.TRIAGE: "medium",
    SorayaMode.TINY_STEP: "small",
    SorayaMode.SAFETY: "small",
}

REVIEW_DOMAINS = {
    "self_harm": "crisis_or_clinical_support",
    "violence": "safety_or_emergency_support",
    "medical": "medical_professional",
    "legal": "legal_professional",
    "financial": "financial_professional",
    "hr_decisioning": "hr_or_manager_review",
    "medium_stakes": "human_review_optional",
}


@dataclass
class AgencyLedgerEntry:
    schema_version: str
    turn_id: int
    timestamp_utc: str
    user_text_sha256: str
    user_text_excerpt: Optional[str]
    user_goal: str
    current_context: str
    selected_route: str
    soraya_mode: str
    cognitive_signals: Dict[str, float]
    risk_signals: Dict[str, bool]
    router_confidence: float
    router_rationale: List[str]
    user_action_required: str
    system_action_taken: str
    next_step_size: str
    dependency_risk_score: float
    user_agency_score: float
    agency_balance_score: float
    agency_delta_estimate: str
    review_required: bool
    review_domain: Optional[str]
    evidence_needed: bool
    evidence_note: str
    storage_policy: str = (
        "MVP ledger is intended for ephemeral session display. "
        "Do not persist sensitive user data unless explicit storage policy is configured."
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


@dataclass
class AgencyLedger:
    entries: List[AgencyLedgerEntry] = field(default_factory=list)

    def add_turn(
        self,
        decision: RouterDecision,
        user_text: str,
        system_action_taken: Optional[str] = None,
        user_goal: Optional[str] = None,
        current_context: Optional[str] = None,
        store_text_excerpt: bool = False,
    ) -> AgencyLedgerEntry:
        entry = create_ledger_entry(
            decision=decision,
            user_text=user_text,
            turn_id=len(self.entries) + 1,
            system_action_taken=system_action_taken,
            user_goal=user_goal,
            current_context=current_context,
            store_text_excerpt=store_text_excerpt,
        )
        self.entries.append(entry)
        return entry

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "turn_count": len(self.entries),
            "summary": summarize_ledger([entry.to_dict() for entry in self.entries]),
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def clear(self) -> None:
        self.entries.clear()


def create_ledger_entry(
    decision: RouterDecision,
    user_text: str,
    turn_id: int = 1,
    system_action_taken: Optional[str] = None,
    user_goal: Optional[str] = None,
    current_context: Optional[str] = None,
    store_text_excerpt: bool = False,
) -> AgencyLedgerEntry:
    mode = decision.soraya_mode
    route = decision.selected_route
    dependency_risk_score = estimate_dependency_risk(decision)
    user_agency_score = estimate_user_agency(decision, dependency_risk_score)
    agency_balance_score = round(user_agency_score - dependency_risk_score, 3)
    review_domain = select_review_domain(decision.risk_signals)
    evidence_needed, evidence_note = estimate_evidence_need(decision)

    return AgencyLedgerEntry(
        schema_version=LEDGER_SCHEMA_VERSION,
        turn_id=turn_id,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        user_text_sha256=hash_text(user_text),
        user_text_excerpt=make_excerpt(user_text) if store_text_excerpt else None,
        user_goal=user_goal or infer_user_goal(user_text, decision),
        current_context=current_context or infer_current_context(decision),
        selected_route=route.value,
        soraya_mode=mode.value,
        cognitive_signals=round_signal_map(decision.cognitive_signals),
        risk_signals=dict(decision.risk_signals),
        router_confidence=round(float(decision.confidence), 3),
        router_rationale=list(decision.rationale),
        user_action_required=decision.user_action_required,
        system_action_taken=system_action_taken or MODE_SYSTEM_ACTIONS.get(mode, "Provided bounded executive-function support."),
        next_step_size=MODE_NEXT_STEP_SIZE.get(mode, "small"),
        dependency_risk_score=dependency_risk_score,
        user_agency_score=user_agency_score,
        agency_balance_score=agency_balance_score,
        agency_delta_estimate=estimate_agency_delta(user_agency_score, dependency_risk_score, decision.review_required),
        review_required=bool(decision.review_required),
        review_domain=review_domain,
        evidence_needed=evidence_needed,
        evidence_note=evidence_note,
    )


def estimate_dependency_risk(decision: RouterDecision) -> float:
    cognitive = decision.cognitive_signals
    score = 0.0
    score += 0.70 * cognitive.get("dependency_risk", 0.0)
    score += 0.10 * cognitive.get("overload", 0.0)
    score += 0.10 * cognitive.get("emotional_drag", 0.0)
    score += 0.10 * cognitive.get("initiation_friction", 0.0)
    return clamp(round(score, 3), 0.0, 1.0)


def estimate_user_agency(decision: RouterDecision, dependency_risk_score: float) -> float:
    mode = decision.soraya_mode
    route = decision.selected_route
    score = 0.70
    if mode == SorayaMode.CLARIFY:
        score += 0.12
    elif mode == SorayaMode.TRIAGE:
        score += 0.08
    elif mode == SorayaMode.TINY_STEP:
        score += 0.10
    elif mode == SorayaMode.SAFETY:
        score += 0.02
    if route == GovernanceRoute.MEDIUM_PATH:
        score -= 0.03
    elif route == GovernanceRoute.DEEP_C3_ICM_PATH:
        score -= 0.08
    score -= 0.25 * dependency_risk_score
    return clamp(round(score, 3), 0.0, 1.0)


def estimate_agency_delta(user_agency_score: float, dependency_risk_score: float, review_required: bool) -> str:
    balance = user_agency_score - dependency_risk_score
    if review_required:
        return "watch_review_required"
    if balance >= 0.55:
        return "positive_agency_preserved"
    if balance >= 0.30:
        return "watch_agency_pressure"
    return "risk_dependency_or_displacement"


def select_review_domain(risk_signals: Dict[str, bool]) -> Optional[str]:
    for key in ["self_harm", "violence", "medical", "legal", "financial", "hr_decisioning", "medium_stakes"]:
        if risk_signals.get(key, False):
            return REVIEW_DOMAINS.get(key)
    return None


def estimate_evidence_need(decision: RouterDecision) -> tuple[bool, str]:
    if decision.selected_route == GovernanceRoute.DEEP_C3_ICM_PATH:
        return True, "Restricted or high-stakes content detected; appropriate human/professional review is needed."
    if decision.selected_route == GovernanceRoute.MEDIUM_PATH:
        return True, "Medium-stakes context detected; claims, policies, deadlines, or stakeholder impacts may need verification."
    return False, "No explicit evidence requirement detected for this low-risk support turn."


def infer_user_goal(user_text: str, decision: RouterDecision) -> str:
    text = (user_text or "").lower()
    if "assignment" in text or "school" in text or "teacher" in text:
        return "make progress on a learning or school task"
    if "resume" in text or "interview" in text:
        return "make progress on a career task"
    if decision.soraya_mode == SorayaMode.TRIAGE:
        return "reduce overload and identify the next priority"
    if decision.soraya_mode == SorayaMode.TINY_STEP:
        return "restore motion on a stuck task"
    if decision.soraya_mode == SorayaMode.SAFETY:
        return "handle a restricted or high-stakes request responsibly"
    return "clarify the next responsible action"


def infer_current_context(decision: RouterDecision) -> str:
    if decision.selected_route == GovernanceRoute.DEEP_C3_ICM_PATH:
        return "high-stakes or restricted domain"
    if decision.selected_route == GovernanceRoute.MEDIUM_PATH:
        return "medium-stakes task context"
    return "low-risk executive-function support"


def summarize_ledger(entry_dicts: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not entry_dicts:
        return {"turn_count": 0}
    n = len(entry_dicts)
    return {
        "turn_count": n,
        "average_dependency_risk": round(sum(e["dependency_risk_score"] for e in entry_dicts) / n, 3),
        "average_user_agency_score": round(sum(e["user_agency_score"] for e in entry_dicts) / n, 3),
        "review_required_count": sum(1 for e in entry_dicts if e["review_required"]),
    }


def hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def make_excerpt(text: str, max_chars: int = 160) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def round_signal_map(signals: Dict[str, float]) -> Dict[str, float]:
    return {key: round(float(value), 3) for key, value in signals.items()}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def format_entry_for_panel(entry) -> str:
    return (
        "### Agency Ledger Entry\n\n"
        f"- **Turn:** `{entry.turn_id}`\n"
        f"- **Route:** `{entry.selected_route}`\n"
        f"- **Mode:** `{entry.soraya_mode}`\n"
        f"- **Dependency risk:** `{entry.dependency_risk_score}`\n"
        f"- **User agency score:** `{entry.user_agency_score}`\n"
        f"- **Agency balance:** `{entry.agency_balance_score}`\n"
        f"- **Agency delta:** `{entry.agency_delta_estimate}`\n"
        f"- **Review required:** `{entry.review_required}`\n"
        f"- **Review domain:** `{entry.review_domain}`\n"
        f"- **Evidence needed:** `{entry.evidence_needed}`\n\n"
        "```json\n"
        + entry.to_json(indent=2)
        + "\n```"
    )
