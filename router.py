from dataclasses import dataclass, asdict
from enum import Enum
import re
from typing import Dict, List


class GovernanceRoute(str, Enum):
    FAST_PATH = "FAST_PATH"
    MEDIUM_PATH = "MEDIUM_PATH"
    DEEP_C3_ICM_PATH = "DEEP_C3_ICM_PATH"


class SorayaMode(str, Enum):
    CLARIFY = "clarify"
    TRIAGE = "triage"
    TINY_STEP = "tiny_step"
    SAFETY = "safety"


@dataclass
class RouterDecision:
    selected_route: GovernanceRoute
    soraya_mode: SorayaMode
    cognitive_signals: Dict[str, float]
    risk_signals: Dict[str, bool]
    user_action_required: str
    review_required: bool
    rationale: List[str]
    confidence: float

    def to_dict(self) -> Dict:
        return asdict(self)


SAFETY_PATTERNS = {
    "self_harm": [r"\bkill myself\b", r"\bsuicide\b", r"\bend my life\b", r"\bhurt myself\b", r"\bself[- ]harm\b"],
    "violence": [r"\bhurt someone\b", r"\battack\b", r"\bweapon\b", r"\bmake a bomb\b"],
    "medical": [r"\bdiagnose\b", r"\bmedication\b", r"\bprescribe\b", r"\bsymptoms\b", r"\bdoctor\b", r"\btherapy\b"],
    "legal": [r"\bsue\b", r"\blawsuit\b", r"\blegal advice\b", r"\bcontract\b", r"\battorney\b"],
    "financial": [r"\binvest\b", r"\bstock\b", r"\bcrypto\b", r"\btaxes\b", r"\bloan\b", r"\bretirement account\b"],
    "hr_decisioning": [r"\bfire this employee\b", r"\bhire this person\b", r"\bpromote\b", r"\bperformance review\b", r"\bdisciplinary action\b"],
}

COGNITIVE_PATTERNS = {
    "ambiguity": [r"\bi don't know where to start\b", r"\bwhere do i start\b", r"\bwhat should i do\b", r"\bnot sure what to do\b", r"\bconfused\b", r"\bunclear\b"],
    "overload": [r"\boverwhelmed\b", r"\btoo much\b", r"\bso many things\b", r"\bi have a lot\b", r"\bcan't keep up\b", r"\beverything at once\b"],
    "initiation_friction": [r"\bprocrastinating\b", r"\bcan't start\b", r"\bstuck\b", r"\bfrozen\b", r"\bavoiding\b", r"\bputting it off\b"],
    "emotional_drag": [r"\bi feel stupid\b", r"\bi'm failing\b", r"\bi hate this\b", r"\bfrustrated\b", r"\bdiscouraged\b", r"\bshame\b"],
    "dependency_risk": [r"\bjust tell me what to do\b", r"\bdecide for me\b", r"\bdo it all for me\b", r"\bi need you to choose\b", r"\bwhat would you do if you were me\b"],
}

MEDIUM_STAKES_PATTERNS = [
    r"\bmanager\b", r"\bworkplace\b", r"\bclient\b", r"\bcustomer\b", r"\bpolicy\b",
    r"\bcompliance\b", r"\bschool assignment\b", r"\bteacher\b", r"\bdeadline\b",
    r"\bresume\b", r"\binterview\b",
]


def normalize_text(text: str) -> str:
    return text.lower().strip()


def pattern_match(text: str, patterns: List[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def score_pattern_group(text: str, patterns: List[str]) -> float:
    matches = sum(1 for pattern in patterns if re.search(pattern, text, flags=re.IGNORECASE))
    if matches == 0:
        return 0.0
    if matches == 1:
        return 0.5
    return 1.0


def detect_risk_signals(user_text: str) -> Dict[str, bool]:
    text = normalize_text(user_text)
    risk_signals = {risk_name: pattern_match(text, patterns) for risk_name, patterns in SAFETY_PATTERNS.items()}
    risk_signals["medium_stakes"] = pattern_match(text, MEDIUM_STAKES_PATTERNS)
    return risk_signals


def detect_cognitive_signals(user_text: str) -> Dict[str, float]:
    text = normalize_text(user_text)
    return {signal_name: score_pattern_group(text, patterns) for signal_name, patterns in COGNITIVE_PATTERNS.items()}


def select_governance_route(risk_signals: Dict[str, bool]) -> GovernanceRoute:
    deep_risks = ["self_harm", "violence", "medical", "legal", "financial", "hr_decisioning"]
    if any(risk_signals.get(risk, False) for risk in deep_risks):
        return GovernanceRoute.DEEP_C3_ICM_PATH
    if risk_signals.get("medium_stakes", False):
        return GovernanceRoute.MEDIUM_PATH
    return GovernanceRoute.FAST_PATH


def select_soraya_mode(route: GovernanceRoute, cognitive_signals: Dict[str, float]) -> SorayaMode:
    if route == GovernanceRoute.DEEP_C3_ICM_PATH:
        return SorayaMode.SAFETY
    dependency = cognitive_signals.get("dependency_risk", 0.0)
    overload = cognitive_signals.get("overload", 0.0)
    ambiguity = cognitive_signals.get("ambiguity", 0.0)
    initiation = cognitive_signals.get("initiation_friction", 0.0)
    emotional = cognitive_signals.get("emotional_drag", 0.0)
    if dependency >= 0.5:
        return SorayaMode.CLARIFY
    if overload >= 0.5:
        return SorayaMode.TRIAGE
    if emotional >= 0.5 and initiation >= 0.5:
        return SorayaMode.TINY_STEP
    if ambiguity >= 0.5:
        return SorayaMode.CLARIFY
    if initiation >= 0.5:
        return SorayaMode.TINY_STEP
    return SorayaMode.CLARIFY


def build_user_action_required(mode: SorayaMode, route: GovernanceRoute) -> str:
    if route == GovernanceRoute.DEEP_C3_ICM_PATH:
        return "Pause and seek appropriate human, professional, or policy review before acting."
    if mode == SorayaMode.CLARIFY:
        return "Answer one clarifying question or choose one goal to work on."
    if mode == SorayaMode.TRIAGE:
        return "Choose the top priority from a shortened list."
    if mode == SorayaMode.TINY_STEP:
        return "Complete one small starter action."
    return "Choose the next responsible action."


def build_rationale(route: GovernanceRoute, mode: SorayaMode, risk_signals: Dict[str, bool], cognitive_signals: Dict[str, float]) -> List[str]:
    rationale = []
    active_risks = [key for key, value in risk_signals.items() if value]
    active_cognitive = [key for key, value in cognitive_signals.items() if value >= 0.5]
    rationale.append(f"Selected governance route: {route.value}.")
    rationale.append(f"Selected Soraya mode: {mode.value}.")
    rationale.append(f"Detected risk/context signals: {', '.join(active_risks)}." if active_risks else "No high-risk domain signals detected.")
    rationale.append(f"Detected executive-function signals: {', '.join(active_cognitive)}." if active_cognitive else "No strong executive-function distress signal detected; defaulting to clarification.")
    return rationale


def estimate_confidence(route: GovernanceRoute, cognitive_signals: Dict[str, float], risk_signals: Dict[str, bool]) -> float:
    if route == GovernanceRoute.DEEP_C3_ICM_PATH:
        return 0.85
    max_cognitive = max(cognitive_signals.values()) if cognitive_signals else 0.0
    if risk_signals.get("medium_stakes", False):
        return 0.75
    if max_cognitive >= 1.0:
        return 0.8
    if max_cognitive >= 0.5:
        return 0.7
    return 0.6


def route_user_turn(user_text: str) -> RouterDecision:
    if not user_text or not user_text.strip():
        return RouterDecision(
            selected_route=GovernanceRoute.FAST_PATH,
            soraya_mode=SorayaMode.CLARIFY,
            cognitive_signals={"ambiguity": 1.0, "overload": 0.0, "initiation_friction": 0.0, "emotional_drag": 0.0, "dependency_risk": 0.0},
            risk_signals={"self_harm": False, "violence": False, "medical": False, "legal": False, "financial": False, "hr_decisioning": False, "medium_stakes": False},
            user_action_required="Name the task or situation you want help with.",
            review_required=False,
            rationale=["Empty or unclear input; defaulting to Clarify Mode."],
            confidence=0.6,
        )
    risk_signals = detect_risk_signals(user_text)
    cognitive_signals = detect_cognitive_signals(user_text)
    route = select_governance_route(risk_signals)
    mode = select_soraya_mode(route, cognitive_signals)
    return RouterDecision(
        selected_route=route,
        soraya_mode=mode,
        cognitive_signals=cognitive_signals,
        risk_signals=risk_signals,
        user_action_required=build_user_action_required(mode, route),
        review_required=route == GovernanceRoute.DEEP_C3_ICM_PATH,
        rationale=build_rationale(route, mode, risk_signals, cognitive_signals),
        confidence=estimate_confidence(route, cognitive_signals, risk_signals),
    )
