import re
from enum import Enum
from typing import Optional

class RequestIntent(str, Enum):
    TARGETED = "targeted"
    BUG_DISCOVERY = "bug_discovery"
    IMPROVEMENT = "improvement"

class IntentResult(str):
    intent: RequestIntent
    confidence: float
    reason: str

    def __new__(cls, intent: RequestIntent, confidence: float = 1.0, reason: str = ""):
        instance = super().__new__(cls, intent.value)
        instance.intent = intent
        instance.confidence = confidence
        instance.reason = reason
        return instance

# High-confidence pattern groups
BUG_DISCOVERY_PATTERNS = [
    r"\b(find|hunt|search|look\s+for|scan|audit|detect|check\s+for)\s+(any\s+)?(all\s+)?(bugs|defects|vulnerabilities|security\s+issues|correctness\s+problems|flaws|issues|errors)\b",
    r"\b(code\s+audit|security\s+audit|bug\s+hunt|bug\s+discovery)\b",
    r"\b(identify\s+the\s+most\s+serious\s+issues|audit\s+the\s+project|find\s+bugs)\b",
    r"\b(are\s+there\s+any\s+bugs|what\s+is\s+broken\s+in\s+this\s+repo)\b"
]

IMPROVEMENT_PATTERNS = [
    r"\b(gimme\s+some\s+ways\s+to\s+improve\s+it|ways\s+to\s+improve(\s+it)?|how\s+can\s+i\s+improve|how\s+to\s+improve)\b",
    r"\b(improve|improvement|improvements|make\s+(it|this)\s+better|recommend\s+improvements|suggestions?)\b",
    r"\b(code\s+review|review\s+(this|the)\s+(project|repo|codebase|code))\b",
    r"\b(best\s+practices|maintainability|refactor|clean\s+up|cleaner\s+code|code\s+quality)\b",
    r"\b(performance\s+bottlenecks|optimize|optimization|enhance|enhancements?)\b"
]

TARGETED_PATTERNS = [
    r"\b(fix|repair|patch|resolve|correct)\s+(the|this|a)?\s*(failing|broken|incorrect|bug|defect|test|error|issue)?\b",
    r"\b(failing\s+test|test_[\w]+\s+fails?|tests?\s+failing|assertionerror|assertion\s+failure)\b",
    r"\b(assert\s+[\w\d\s=<>!]+|expected\s+[\w\d\s]+but\s+got)\b",
    r"\b(traceback|stacktrace|exception\s+thrown|nullpointer|zerodivision|typeerror|valueerror|indexerror)\b",
    r"\b(incorrect\s+subtraction|math_utils|broken\s+function|returns?\s+[\w\d\s]+instead\s+of)\b"
]

def classify_intent(query: str, explicit_mode: Optional[str] = None, has_reproduction_error: bool = False) -> IntentResult:
    """
    Classify request into TARGETED, BUG_DISCOVERY, or IMPROVEMENT.
    Fast, deterministic, and avoids wasteful LLM calls.
    """
    if explicit_mode and explicit_mode.lower() in [RequestIntent.TARGETED.value, RequestIntent.BUG_DISCOVERY.value, RequestIntent.IMPROVEMENT.value]:
        return IntentResult(RequestIntent(explicit_mode.lower()), confidence=1.0, reason="explicit_mode")

    if not query or not query.strip():
        return IntentResult(RequestIntent.TARGETED, confidence=0.5, reason="empty_query_default")

    text = query.strip().lower()

    # If reproduction test failed with assertion/error, strong signal for targeted fix
    if has_reproduction_error and any(re.search(p, text) for p in TARGETED_PATTERNS):
        return IntentResult(RequestIntent.TARGETED, confidence=0.95, reason="reproduction_error_and_pattern")

    # Check Bug Discovery patterns first
    for pattern in BUG_DISCOVERY_PATTERNS:
        if re.search(pattern, text):
            return IntentResult(RequestIntent.BUG_DISCOVERY, confidence=0.9, reason="bug_discovery_pattern")

    # Check Improvement & Review patterns
    for pattern in IMPROVEMENT_PATTERNS:
        if re.search(pattern, text):
            return IntentResult(RequestIntent.IMPROVEMENT, confidence=0.9, reason="improvement_pattern")

    # Check Targeted repair patterns
    for pattern in TARGETED_PATTERNS:
        if re.search(pattern, text):
            return IntentResult(RequestIntent.TARGETED, confidence=0.9, reason="targeted_pattern")

    # Fallback heuristic:
    # If the user mentions specific filenames or function keywords like "def ", "class ", ".py", ".ts"
    if re.search(r"\b[\w_]+\.(py|ts|js|jsx|tsx|rs|go)\b", text) or "def " in text or "function " in text:
        return IntentResult(RequestIntent.TARGETED, confidence=0.75, reason="filename_or_keyword")

    # Open-ended inquiry without specific defect indicators defaults to general review & improvement
    return IntentResult(RequestIntent.IMPROVEMENT, confidence=0.7, reason="open_ended_default")
