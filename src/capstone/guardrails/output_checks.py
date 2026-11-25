"""Output guardrails: checked on every reply before it leaves the service."""
import re

# A reply may never claim an approval has happened: only a recorded decision by a signatory is an approval.
APPROVAL_CLAIMS = (
    r"has been approved", r"\bis approved\b", r"proceeding with approval", r"approving now", r"i (have )?approved",
)
# Protected attributes and proxies must never appear in a rationale (fair-lending standard 4.2 and 4.3).
FORBIDDEN_RATIONALE_TERMS = (
    "community", "religion", "caste", "gender", "ethnic", "minority", "language", "neighbourhood", "slum", "prime location",
    "educated", "college", "mba", "single mother", "name suggests",
)


def violations(text: str, check_terms: bool = False) -> list[str]:
  """Approval claims are checked on every reply. Forbidden terms are checked on decision rationales only
  (a policy answer may legitimately quote the fair-lending list of prohibited proxies)."""
  lowered = text.lower()
  found = [f"approval_claim:{pattern}" for pattern in APPROVAL_CLAIMS if re.search(pattern, lowered)]
  if check_terms:
    found += [f"forbidden_term:{term}" for term in FORBIDDEN_RATIONALE_TERMS if re.search(rf"\b{re.escape(term)}", lowered)]
  return found


def enforce(text: str, fallback: str, check_terms: bool = False) -> tuple[str, list[str]]:
  """Return the text if clean, otherwise the safe fallback and the list of violations."""
  problems = violations(text, check_terms)
  return (fallback, problems) if problems else (text, [])
