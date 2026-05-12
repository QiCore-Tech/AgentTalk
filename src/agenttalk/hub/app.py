from __future__ import annotations

import asyncio
import json
import logging
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.websockets import WebSocket
from fastapi.responses import JSONResponse

from agenttalk.hub.errors import api_error
from agenttalk.hub.models import (
    AgentContextUpdateRequest,
    AgentHealthReport,
    AgentListResponse,
    AgentStatus,
    AgentUpsertRequest,
    ErrorResponse,
    HealthResponse,
    MessageCreateRequest,
    MessageResponseUpdateRequest,
    MessageStatusUpdateRequest,
    PendingMessageResponse,
    RelayHeartbeatRequest,
    RelayRegisterRequest,
)
from agenttalk.hub.settings import HubSettings
from agenttalk.hub.store import AgentFilters, HubStore
from agenttalk.hub.pty_manager import pty_manager
from agenttalk.hub.relay_connection_manager import relay_manager, RelayConnection
from agenttalk.tmux import TmuxClient
from agenttalk.feishu.service import FeishuAgentTalkService
from agenttalk.feishu.worker import FeishuEventHandler, FeishuLongConnectionWorker, LarkMessenger




def create_app(settings: HubSettings) -> FastAPI:
    store = HubStore(
        settings.database_path,
        heartbeat_ttl_seconds=settings.heartbeat_ttl_seconds,
    )

    feishu_messenger: LarkMessenger | None = None
    feishu_service: FeishuAgentTalkService | None = None

    async def capture_pty_outputs() -> None:
        """Background task to capture PTY outputs periodically."""
        while True:
            try:
                await asyncio.sleep(10)
                for short_id in pty_manager.list_sessions():
                    try:
                        output = pty_manager.capture_output(short_id, max_lines=50)
                        if output:
                            from agenttalk.hub.models import AgentContextUpdateRequest
                            store.update_agent_context(short_id, AgentContextUpdateRequest(context=output))
                    except Exception:
                        pass
            except Exception:
                pass

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal feishu_messenger, feishu_service
        app.state.settings = settings
        app.state.store = store
        if settings.feishu_enable:
            feishu_messenger = LarkMessenger(settings.feishu_app_id, settings.feishu_app_secret)
            feishu_service = FeishuAgentTalkService(store, web_base_url=settings.public_base_url)
            handler = FeishuEventHandler(feishu_service, feishu_messenger)
            worker = FeishuLongConnectionWorker(
                app_id=settings.feishu_app_id,
                app_secret=settings.feishu_app_secret,
                handler=handler,
            )
            worker.start_background()
            app.state.feishu_worker = worker
        # Start PTY capture background task
        asyncio.create_task(capture_pty_outputs())
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

    def maybe_alert_feishu(short_id: str, alert_type: str, message: str, owner: str = "") -> None:
        if not settings.feishu_enable or feishu_messenger is None or feishu_service is None:
            return
        try:
            feishu_service.send_alert(
                feishu_messenger, short_id, alert_type, message,
                owner=owner, chat_id=settings.feishu_alert_chat_id,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"Feishu alert failed: {exc}")

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.websocket("/ws/terminal/{short_id}")
    async def terminal_websocket(websocket: WebSocket, short_id: str):
        await websocket.accept()
        agent = store.get_agent(short_id)
        if agent is None:
            await websocket.send_text(f"Agent not found: {short_id}\r\n")
            await websocket.close()
            return
        tmux = TmuxClient()

        def capture_registered_target() -> str:
            if hasattr(tmux, "capture_output"):
                return tmux.capture_output(agent.tmux_target, lines=120)
            return tmux.capture_pane(agent.tmux_target, lines=120)

        async def send_snapshot(*, force: bool = False) -> str:
            try:
                output = capture_registered_target().replace("\n", "\r\n")
            except Exception as exc:
                output = f"Unable to capture registered tmux target {agent.tmux_target}: {exc}\r\n"
            if force or output != send_snapshot.last_output:
                send_snapshot.last_output = output
                await websocket.send_text("\x1b[2J\x1b[H" + output)
            return output

        send_snapshot.last_output = ""  # type: ignore[attr-defined]

        async def stream_snapshots() -> None:
            await send_snapshot(force=True)
            while True:
                await asyncio.sleep(0.5)
                await send_snapshot()

        stream_task = asyncio.create_task(stream_snapshots())
        try:
            while True:
                data = await websocket.receive_text()
                try:
                    tmux.inject_text(agent.tmux_target, data, submit=False)
                except Exception as exc:
                    await websocket.send_text(f"\r\nUnable to write tmux pane: {exc}\r\n")
        except Exception:
            return
        finally:
            stream_task.cancel()

    @app.websocket("/ws/relay-terminal/{machine_id}")
    async def relay_terminal_websocket(websocket: WebSocket, machine_id: str):
        """Reverse tunnel endpoint for relays to connect to Hub."""
        await websocket.accept()

        # Wait for hello message with auth
        try:
            hello_raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            hello = json.loads(hello_raw)
            if hello.get("type") != "hello":
                await websocket.close(code=4001, reason="Expected hello message")
                return
            token = hello.get("token", "")
            if token != settings.token:
                await websocket.close(code=4001, reason="Invalid token")
                return
        except (asyncio.TimeoutError, json.JSONDecodeError):
            await websocket.close(code=4001, reason="Auth timeout or invalid JSON")
            return

        # Register relay connection
        conn = RelayConnection(machine_id, websocket)
        relay_manager.register(machine_id, conn)

        try:
            while True:
                msg_raw = await websocket.receive_text()
                msg = json.loads(msg_raw)
                msg_type = msg.get("type", "")
                session_id = msg.get("session_id", "")

                if msg_type == "terminal_output":
                    await relay_manager.handle_relay_output(session_id, msg.get("data", ""))
                elif msg_type == "terminal_error":
                    await relay_manager.handle_relay_error(session_id, msg.get("message", ""))
                elif msg_type == "ping":
                    await conn.send({"type": "pong", "session_id": session_id})
        except Exception as exc:
            logger.warning("Relay terminal websocket error for %s: %s", machine_id, exc)
        finally:
            relay_manager.unregister(machine_id)

    @app.websocket("/ws/pty/{short_id}")
    async def pty_websocket(websocket: WebSocket, short_id: str):
        await websocket.accept()
        agent = store.get_agent(short_id)
        if agent is None:
            await websocket.close(code=4004, reason=f"Agent not found: {short_id}")
            return

        # Try reverse tunnel first (for remote agents)
        if relay_manager.is_connected(agent.machine_id):
            session_id = await relay_manager.open_terminal(agent.machine_id, short_id, websocket)
            if session_id:
                try:
                    while True:
                        message = await websocket.receive()
                        if "text" in message:
                            text = message["text"]
                            if text.startswith("\x01"):
                                try:
                                    _, rows, cols = text.split(":")
                                    await relay_manager.send_resize(session_id, int(rows), int(cols))
                                except (ValueError, IndexError):
                                    pass
                            else:
                                await relay_manager.send_input(session_id, text)
                        elif "bytes" in message:
                            await relay_manager.send_input(session_id, message["bytes"].decode("utf-8", errors="replace"))
                except Exception:
                    pass
                finally:
                    await relay_manager.close_terminal(session_id)
                return

        # Fallback: local PTY (for agents on same machine as Hub)
        await websocket.send_text("\x1b[32m[Connected to PTY]\x1b[0m\r\n")
        try:
            session = pty_manager.get_or_create(short_id, agent.tmux_target)
        except Exception as exc:
            await websocket.send_text(f"\x1b[31m[Failed to create PTY: {exc}]\x1b[0m\r\n")
            return

        read_task = None
        write_task = None
        try:
            read_task = asyncio.create_task(session.start_reader(websocket))
            write_task = asyncio.create_task(session.start_writer())

            while True:
                message = await websocket.receive()
                if "text" in message:
                    text = message["text"]
                    if text.startswith("\x01"):
                        try:
                            _, rows, cols = text.split(":")
                            session.set_size(int(rows), int(cols))
                        except (ValueError, IndexError):
                            pass
                    else:
                        session.write(text)
                elif "bytes" in message:
                    session.write(message["bytes"])
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"PTY WebSocket error for {short_id}: {exc}")
        finally:
            if read_task and not read_task.done():
                read_task.cancel()
            if write_task and not write_task.done():
                write_task.cancel()
            try:
                await websocket.close()
            except Exception:
                pass

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

    @app.delete(
        "/api/agents/{short_id}",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def delete_agent(short_id: str, hub_store: HubStore = Depends(get_store)):
        agent = hub_store.get_agent(short_id)
        if agent is None:
            raise api_error(404, "agent_not_found", f"Agent not found: {short_id}")
        hub_store.delete_agent(short_id)
        return {"deleted": True, "short_id": short_id}

    @app.post(
        "/api/agents/{short_id}/health",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def report_agent_health(
        short_id: str,
        report: AgentHealthReport,
        hub_store: HubStore = Depends(get_store),
    ):
        agent = hub_store.get_agent(short_id)
        if agent is None:
            raise api_error(404, "agent_not_found", f"Agent not found: {short_id}")
        
        previous_status = agent.status
        updated = hub_store.report_health(report)
        
        # Trigger alerts on status degradation
        if report.status in (AgentStatus.CRASHED, AgentStatus.ERROR) and previous_status not in (AgentStatus.CRASHED, AgentStatus.ERROR):
            alert_type = "crashed" if report.status == AgentStatus.CRASHED else "error"
            owner_info = f" 创建者: {agent.owner}" if agent.owner else ""
            if report.detected_errors:
                alert_msg = f"Agent {short_id}{owner_info} 状态异常: {report.status.value}\n检测到错误: {', '.join(report.detected_errors[:5])}"
            else:
                alert_msg = f"Agent {short_id}{owner_info} 状态异常: {report.status.value}\n进程或 pane 已停止"
            hub_store.create_alert(short_id, alert_type, alert_msg)
            maybe_alert_feishu(short_id, alert_type, alert_msg, agent.owner)
        
        # Auto-resume: only works when LLM monitoring is enabled and per-agent config allows it
        llm_enabled = hub_store.get_config("llm.enabled") == "1"
        agent_auto_resume_enabled, agent_auto_resume_message = hub_store.get_agent_auto_resume(short_id)
        if llm_enabled and agent_auto_resume_enabled and report.detected_pauses:
            # Only auto-resume if not already in error/crashed state
            if report.status not in (AgentStatus.CRASHED, AgentStatus.ERROR):
                try:
                    session = pty_manager.get_or_create(short_id, agent.tmux_target)
                    session.write(agent_auto_resume_message + "\n")
                    # Also update agent status to working
                    hub_store.update_agent_status(short_id, AgentStatus.WORKING)
                except Exception:
                    pass  # Fail silently if auto-resume fails
        
        return updated

    @app.get(
        "/api/agents/{short_id}/alerts",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}},
    )
    def list_agent_alerts(
        short_id: str,
        unacknowledged_only: bool = False,
        hub_store: HubStore = Depends(get_store),
    ):
        return {"alerts": hub_store.list_alerts(short_id=short_id, unacknowledged_only=unacknowledged_only)}

    @app.post(
        "/api/agents/{short_id}/alerts/{alert_id}/acknowledge",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def acknowledge_alert(
        short_id: str,
        alert_id: int,
        hub_store: HubStore = Depends(get_store),
    ):
        if not hub_store.acknowledge_alert(alert_id):
            raise api_error(404, "alert_not_found", f"Alert not found: {alert_id}")
        return {"acknowledged": True, "alert_id": alert_id}

    @app.post(
        "/api/messages",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def create_message(request: MessageCreateRequest, hub_store: HubStore = Depends(get_store)):
        message, error = hub_store.create_message(request)
        if error == "target_not_found":
            raise api_error(404, "target_not_found", f"Target agent not found: {request.to}")
        if error == "target_offline":
            raise api_error(409, "target_offline", f"Target agent is offline: {request.to}")
        return message

    @app.get(
        "/api/messages/{message_id}",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def get_message(message_id: str, hub_store: HubStore = Depends(get_store)):
        message = hub_store.get_message(message_id)
        if message is None:
            raise api_error(404, "message_not_found", f"Message not found: {message_id}")
        return message

    @app.get(
        "/api/relays/{machine_id}/messages/next",
        response_model=PendingMessageResponse,
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}},
    )
    def next_relay_message(machine_id: str, hub_store: HubStore = Depends(get_store)) -> PendingMessageResponse:
        return PendingMessageResponse(message=hub_store.next_message_for_relay(machine_id))

    @app.post(
        "/api/messages/{message_id}/status",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def update_message_status(
        message_id: str,
        request: MessageStatusUpdateRequest,
        hub_store: HubStore = Depends(get_store),
    ):
        message = hub_store.update_message_status(message_id, request.status, request.error)
        if message is None:
            raise api_error(404, "message_not_found", f"Message not found: {message_id}")
        return message

    @app.get(
        "/api/messages/{message_id}/response",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def get_message_response(message_id: str, hub_store: HubStore = Depends(get_store)):
        response = hub_store.get_message_response(message_id)
        if response is None:
            raise api_error(404, "message_not_found", f"Message not found: {message_id}")
        return response

    @app.post(
        "/api/messages/{message_id}/response",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def update_message_response(
        message_id: str,
        request: MessageResponseUpdateRequest,
        hub_store: HubStore = Depends(get_store),
    ):
        response = hub_store.update_message_response(message_id, request)
        if response is None:
            raise api_error(404, "message_not_found", f"Message not found: {message_id}")
        return response

    @app.get(
        "/api/agents/{short_id}/context",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def get_agent_context(short_id: str, hub_store: HubStore = Depends(get_store)):
        context = hub_store.get_agent_context(short_id)
        if context is None:
            raise api_error(404, "agent_not_found", f"Agent not found: {short_id}")
        return context

    @app.post(
        "/api/agents/{short_id}/context",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def update_agent_context(
        short_id: str,
        request: AgentContextUpdateRequest,
        hub_store: HubStore = Depends(get_store),
    ):
        context = hub_store.update_agent_context(short_id, request)
        if context is None:
            raise api_error(404, "agent_not_found", f"Agent not found: {short_id}")
        return context

    @app.post(
        "/api/agents/{short_id}/pty",
        dependencies=[Depends(require_token)],
        responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def write_to_agent_pty(
        short_id: str,
        request: dict,
        hub_store: HubStore = Depends(get_store),
    ):
        agent = hub_store.get_agent(short_id)
        if agent is None:
            raise api_error(404, "agent_not_found", f"Agent not found: {short_id}")
        
        text = request.get("text", "")
        if not text:
            raise api_error(400, "bad_request", "Missing 'text' field")
        
        # Write directly to PTY
        success = pty_manager.write_to_agent(short_id, text)
        if not success:
            # PTY not active, create one
            session = pty_manager.get_or_create(short_id, agent.tmux_target)
            session.write(text)
        
        return {"written": True, "short_id": short_id}

    @app.get("/api/config/llm")
    def get_llm_config(_: None = Depends(require_token)) -> dict:
        store = get_store()
        base_url = store.get_config("llm.base_url") or ""
        api_key = store.get_config("llm.api_key") or ""
        model = store.get_config("llm.model") or "gpt-4o-mini"
        enabled = store.get_config("llm.enabled") == "1"
        return {"base_url": base_url, "api_key": api_key, "model": model, "enabled": enabled}

    @app.post("/api/config/llm")
    def set_llm_config(body: dict, _: None = Depends(require_token)) -> dict:
        store = get_store()
        store.set_config("llm.base_url", body.get("base_url", ""))
        store.set_config("llm.api_key", body.get("api_key", ""))
        store.set_config("llm.model", body.get("model", "gpt-4o-mini"))
        store.set_config("llm.enabled", "1" if body.get("enabled", False) else "0")
        return {"ok": True}

    @app.get("/api/agents/{short_id}/auto_resume")
    def get_agent_auto_resume(
        short_id: str,
        hub_store: HubStore = Depends(get_store),
        _: None = Depends(require_token),
    ) -> dict:
        agent = hub_store.get_agent(short_id)
        if agent is None:
            raise api_error(404, "agent_not_found", f"Agent not found: {short_id}")
        enabled, message = hub_store.get_agent_auto_resume(short_id)
        return {"enabled": enabled, "message": message}

    @app.post("/api/agents/{short_id}/auto_resume")
    def set_agent_auto_resume(
        short_id: str,
        body: dict,
        hub_store: HubStore = Depends(get_store),
        _: None = Depends(require_token),
    ) -> dict:
        agent = hub_store.get_agent(short_id)
        if agent is None:
            raise api_error(404, "agent_not_found", f"Agent not found: {short_id}")
        hub_store.set_agent_auto_resume(
            short_id,
            enabled=body.get("enabled", True),
            message=body.get("message", "继续"),
        )
        return {"ok": True}

    if settings.web_dist_path and settings.web_dist_path.exists():
        app.mount("/", StaticFiles(directory=settings.web_dist_path, html=True), name="web")

    return app

    return app
