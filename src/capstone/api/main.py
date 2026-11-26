"""FastAPI application factory. Run:  uvicorn capstone.api.main:get_app --factory --host 0.0.0.0 --port 8000"""
import logging
from typing import Any, Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from capstone.api.routes import router
from capstone.observability.logging import configure_logging
from capstone.observability.tracing import start_trace
from capstone.workflows.checkpoints import open_checkpointer
from capstone.workflows.graph import build_graph

logger = logging.getLogger(__name__)


def _default_assistant_factory() -> Callable[[], Any]:
  """Built on first use, so the service starts (and /health answers) even before the policy index exists."""
  holder: dict[str, Any] = {}

  def get():
    if "assistant" not in holder:
      from capstone.rag.corpus import load_policy_chunks
      from capstone.rag.index import PolicyIndex
      from capstone.rag.retrieval import Retriever
      from capstone.services.assistant import Assistant
      holder["assistant"] = Assistant(Retriever(PolicyIndex(), load_policy_chunks()))
    return holder["assistant"]
  return get


def create_app(graph: Optional[Any] = None, assistant_factory: Optional[Callable[[], Any]] = None) -> FastAPI:
  app = FastAPI(title="WealthPilot", version="1.0.0", description="SME loan underwriting and credit research assistant")
  app.state.graph = graph if graph is not None else build_graph(open_checkpointer())
  app.state.assistant = assistant_factory or _default_assistant_factory()
  app.include_router(router)

  @app.middleware("http")
  async def trace_requests(request: Request, call_next):
    with start_trace("http_request", session_id=request.headers.get("X-Session-Id"),
                     user_id=request.headers.get("X-User-Id"),
                     method=request.method, path=request.url.path) as trace_id:
      response = await call_next(request)
      response.headers["X-Trace-Id"] = trace_id
      return response

  @app.exception_handler(Exception)
  async def unexpected(request: Request, error: Exception):
    logger.exception("unhandled error on %s", request.url.path)  # details go to the log, never to the caller
    return JSONResponse(status_code=500, content={"detail": "Internal error."})

  return app


def get_app() -> FastAPI:
  configure_logging()
  return create_app()

