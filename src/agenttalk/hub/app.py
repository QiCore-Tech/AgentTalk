from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agenttalk.hub.errors import api_error
from agenttalk.hub.models import (
    AgentListResponse,
    AgentStatus,
    AgentUpsertRequest,
    ErrorResponse,
    HealthResponse,
    RelayHeartbeatRequest,
    RelayRegisterRequest,
)
from agenttalk.hub.settings import HubSettings
from agenttalk.hub.store import AgentFilters, HubStore


def create_app(settings: HubSettings) -> FastAPI:
    store = HubStore(
        settings.database_path,
        heartbeat_ttl_seconds=settings.heartbeat_ttl_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.store = store
        yield

    app = FastAPI(title="AgentTalk Hub", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": str(exc)}},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": str(exc.detail)}},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        if hasattr(exc, "status_code") and hasattr(exc, "detail"):
            detail = exc.detail
            if isinstance(detail, dict) and "error" in detail:
                return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
        )

    def require_token(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {settings.token}"
        if authorization != expected:
            raise api_error(401, "unauthorized", "Missing or invalid bearer token")

    def get_store() -> HubStore:
        return store

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.post(
        "/api/relays/register",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}},
    )
    def register_relay(request: RelayRegisterRequest, hub_store: HubStore = Depends(get_store)):
        return hub_store.register_relay(request)

    @app.post(
        "/api/relays/heartbeat",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def relay_heartbeat(request: RelayHeartbeatRequest, hub_store: HubStore = Depends(get_store)):
        relay = hub_store.heartbeat(request.machine_id)
        if relay is None:
            raise api_error(404, "relay_not_found", f"Relay not found: {request.machine_id}")
        return relay

    @app.put(
        "/api/agents",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def upsert_agent(request: AgentUpsertRequest, hub_store: HubStore = Depends(get_store)):
        agent = hub_store.upsert_agent(request)
        if agent is None:
            raise api_error(404, "relay_not_found", f"Relay not found: {request.machine_id}")
        return agent

    @app.get(
        "/api/agents",
        response_model=AgentListResponse,
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}},
    )
    def list_agents(
        owner: str | None = None,
        machine_id: str | None = None,
        status: AgentStatus | None = None,
        hub_store: HubStore = Depends(get_store),
    ) -> AgentListResponse:
        agents = hub_store.list_agents(AgentFilters(owner=owner, machine_id=machine_id, status=status))
        return AgentListResponse(agents=agents)

    @app.get(
        "/api/agents/{short_id}",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def get_agent(short_id: str, hub_store: HubStore = Depends(get_store)):
        agent = hub_store.get_agent(short_id)
        if agent is None:
            raise api_error(404, "agent_not_found", f"Agent not found: {short_id}")
        return agent

    return app
