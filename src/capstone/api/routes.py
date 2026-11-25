"""HTTP routes. Thin: every rule lives in the assistant, the workflow and the tools."""
import hmac
import logging
from dataclasses import asdict
from typing import Callable, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from capstone.settings import get_settings
from capstone.tools.actions import DECISION_OUTCOMES
from capstone.workflows import graph as workflow

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_TEXT_CHARS = 6000


class AssistRequest(BaseModel):
  text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


class DecisionRequest(BaseModel):
  outcome: str
  decided_by: str = Field(min_length=1, max_length=40)
  note: str = Field(default="", max_length=500)


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
  """State-changing calls need the service API key. With no key configured they are switched off, never open."""
  configured = get_settings().api_key
  if not configured:
    raise HTTPException(status_code=503, detail="State-changing endpoints are disabled: API_KEY is not configured.")
  if not x_api_key or not hmac.compare_digest(x_api_key, configured):
    raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@router.get("/health")
def health() -> dict:
  return {"status": "ok"}


@router.post("/assist")
def assist(body: AssistRequest, request: Request) -> dict:
  """Ask a policy question or submit application text. Read-only: nothing is decided here."""
  response = request.app.state.assistant().handle(body.text)
  return asdict(response)


@router.post("/applications/{application_id}/underwrite", dependencies=[Depends(require_api_key)])
def underwrite(application_id: str, request: Request) -> dict:
  """Run the workflow. It finishes (automatic cases) or pauses for a named human."""
  result = workflow.start(request.app.state.graph, application_id)
  if result.get("outcome") == "intake_failed":
    raise HTTPException(status_code=404, detail=f"Unknown application '{application_id}'.")
  return result


@router.get("/applications/{application_id}")
def application_status(application_id: str, request: Request) -> dict:
  graph = request.app.state.graph
  snapshot = graph.get_state(workflow._config(application_id))
  if not snapshot.values:
    raise HTTPException(status_code=404, detail="No workflow run for this application.")
  values = snapshot.values
  return {"waiting": bool(snapshot.next), "outcome": values.get("outcome"), "trail": values.get("trail", []),
          "bureau_source": values.get("bureau_source"), "decision": values.get("decision")}


@router.post("/applications/{application_id}/decision", dependencies=[Depends(require_api_key)])
def decide(application_id: str, body: DecisionRequest, request: Request) -> dict:
  """A named signatory answers a paused review. The signatory's authority is checked in code, not here."""
  graph = request.app.state.graph
  if body.outcome not in DECISION_OUTCOMES:
    raise HTTPException(status_code=422, detail=f"outcome must be one of {', '.join(DECISION_OUTCOMES)}")
  if not workflow.is_waiting(graph, application_id):
    raise HTTPException(status_code=409, detail="This application is not waiting for a human decision.")
  return workflow.resume(graph, application_id, body.model_dump())
