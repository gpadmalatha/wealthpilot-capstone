"""Input guardrails: run BEFORE any model sees the text.

- strip_proxies removes fair-lending proxies (name, place, language, education) from application text, so a model
  cannot be influenced by them even by accident.
- check_request catches prompt injection, requests to let protected circumstances sway a decision, and pressure to
  approve without the required signatory.
"""
import re
from dataclasses import dataclass, field

ALLOW, INJECTION, FAIR_LENDING, APPROVAL_PRESSURE = "allow", "injection", "fair_lending", "approval_pressure"

INJECTION_PATTERNS = (
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
    r"disregard (the |your )?(system|previous|prior) (prompt|instructions|rules)",
    r"reveal (your |the )?(system )?prompt",
    r"you are now\b",
    r"act as (an? )?(unrestricted|jailbroken)",
)

# Personal circumstances that may never sway a credit decision (fair-lending standard, protected attributes).
PROTECTED_CUES = (
    r"single (mother|father|parent)", r"\bmarital\b", r"\b(un)?married\b", r"\bdivorced\b", r"\bwidow", r"\bpregnan",
    r"\bgender\b", r"\bfemale\b", r"\bcaste\b", r"\breligio", r"\bethnic", r"\bdisabilit",
    r"because (she|he) is\b",
)
INFLUENCE_CUES = (r"\bshould\b", r"\bpush\b", r"\bover the line\b", r"\bboost\b", r"\bexception\b", r"\bweigh\b", r"\bcount\b", r"\bfavou?r\b")

PRESSURE_PATTERNS = (
    r"signature later", r"sign(ed)? later", r"verbally (agreed|approved)", r"already (agreed|approved)",
    r"approve (this|it|the)\b.{0,60}\b(now|immediately|today)\b",
)

# A sentence mentioning any of these is dropped from application text: they describe who the applicant is or where
# and how they applied, never the financials.
PROXY_MARKERS = (
    "proprietor", "registered office", "pin ", "pincode", "submitted in", "language", "mba", "college", "institute",
    "university", "neighbourhood", "neighborhood", "owner", "director", "founder", "resident", "native",
)
APPLICATION_CUE = re.compile(r"\b(term loan request|loan request|requesting|requested)\b.*\b(rupees|inr)\b", re.IGNORECASE | re.DOTALL)
MIN_NUMBERS_IN_APPLICATION = 3


@dataclass
class InputVerdict:
  action: str = ALLOW
  reasons: list[str] = field(default_factory=list)


def looks_like_application(text: str) -> bool:
  return bool(APPLICATION_CUE.search(text)) and len(re.findall(r"\d[\d,]{3,}", text)) >= MIN_NUMBERS_IN_APPLICATION


def check_request(text: str) -> InputVerdict:
  lowered = text.lower()
  if any(re.search(pattern, lowered) for pattern in INJECTION_PATTERNS):
    return InputVerdict(INJECTION, ["prompt_injection_pattern"])
  if any(re.search(pattern, lowered) for pattern in PRESSURE_PATTERNS):
    return InputVerdict(APPROVAL_PRESSURE, ["approval_without_signatory"])
  if looks_like_application(text):
    return InputVerdict(ALLOW)  # proxies inside an application are stripped, not refused
  if any(re.search(pattern, lowered) for pattern in PROTECTED_CUES) and any(re.search(pattern, lowered) for pattern in INFLUENCE_CUES):
    return InputVerdict(FAIR_LENDING, ["protected_circumstance_offered_as_reason"])
  return InputVerdict(ALLOW)


def strip_proxies(text: str) -> tuple[str, int]:
  """Drop every sentence that mentions a proxy marker. Returns the cleaned text and how many sentences were removed."""
  sentences = re.split(r"(?<=[.;])\s+", text.strip())
  kept = [s for s in sentences if not any(marker in s.lower() for marker in PROXY_MARKERS)]
  return " ".join(kept), len(sentences) - len(kept)
