from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from agenttalk.feishu.commands import parse_command
from agenttalk.feishu.render import FeishuReply, text_reply
from agenttalk.feishu.service import FeishuAgentTalkService, FeishuOperator

logger = logging.getLogger(__name__)


class FeishuMessenger(Protocol):
    def send_reply(self, receive_id: str, reply: FeishuReply, *, receive_id_type: str = "chat_id") -> None: ...


@dataclass(frozen=True)
class FeishuEvent:
    text: str
    receive_id: str
    receive_id_type: str = "chat_id"
    open_id: str = ""
    chat_id: str = ""


class FeishuEventHandler:
    def __init__(self, service: FeishuAgentTalkService, messenger: FeishuMessenger, *, bot_id: int | None = None, store=None) -> None:
        self.service = service
        self.messenger = messenger
        self.bot_id = bot_id
        self.store = store

    def handle_event(self, event: FeishuEvent) -> FeishuReply:
        # Private chat: inject user context if bound
        if event.receive_id_type == "open_id" and self.store and self.bot_id:
            user_id = self.store.find_user_by_open_id(event.open_id, self.bot_id)
            if user_id:
                # User is bound; optionally filter commands to their agents
                pass  # Commands are already user-scoped via service/store
            else:
                # Not bound; prompt user to bind
                reply = text_reply("请先绑定账号。发送 /bind <你的Hub Token>")
                self.messenger.send_reply(event.receive_id, reply, receive_id_type=event.receive_id_type)
                return reply

        reply = self.service.handle(parse_command(event.text), FeishuOperator(open_id=event.open_id, chat_id=event.chat_id))
        self.messenger.send_reply(event.receive_id, reply, receive_id_type=event.receive_id_type)
        return reply


class LarkMessenger:
    def __init__(self, app_id: str, app_secret: str) -> None:
        import lark_oapi as lark

        self._client = lark.Client.builder().app_id(app_id).app_secret(app_secret).log_level(lark.LogLevel.INFO).build()

    def send_reply(self, receive_id: str, reply: FeishuReply, *, receive_id_type: str = "chat_id") -> None:
        import lark_oapi.api.im.v1 as im_v1

        content = (
            json.dumps(reply.content, ensure_ascii=False)
            if isinstance(reply.content, dict)
            else json.dumps({"text": reply.content}, ensure_ascii=False)
        )
        request = (
            im_v1.CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                im_v1.CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type(reply.msg_type)
                .content(content)
                .build()
            )
            .build()
        )
        response = self._client.im.v1.message.create(request)
        if not response.success():
            raise RuntimeError(f"Feishu send failed: code={response.code}, msg={response.msg}")

    def send_to_chat(self, chat_id: str, reply: FeishuReply) -> None:
        if not chat_id:
            raise RuntimeError("chat_id is required for send_to_chat")
        self.send_reply(chat_id, reply, receive_id_type="chat_id")


class FeishuLongConnectionWorker:
    def __init__(self, *, app_id: str, app_secret: str, handler: FeishuEventHandler) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.handler = handler
        self._thread: threading.Thread | None = None

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run_forever, name="agenttalk-feishu", daemon=True)
        self._thread.start()

    def run_forever(self) -> None:
        import asyncio
        import lark_oapi as lark

        # Create a new event loop for this thread to avoid conflicts with uvicorn
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def on_message(data: Any) -> None:
            try:
                event = extract_event(data)
                self.handler.handle_event(event)
            except Exception:
                logger.exception("failed to handle Feishu event")

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_message)
            .build()
        )
        client = lark.ws.Client(self.app_id, self.app_secret, event_handler=event_handler, log_level=lark.LogLevel.INFO)
        client.start()


def extract_event(data: Any) -> FeishuEvent:
    event = getattr(data, "event", data)
    message = getattr(event, "message", None)
    sender = getattr(event, "sender", None)
    text = extract_text_from_message(message)
    chat_id = str(getattr(message, "chat_id", "") or getattr(message, "chatId", "") or "")
    open_id = ""
    if sender is not None:
        sender_id = getattr(sender, "sender_id", None)
        open_id = str(getattr(sender_id, "open_id", "") or getattr(sender_id, "openId", "") or "")
    receive_id = chat_id or open_id
    receive_id_type = "chat_id" if chat_id else "open_id"
    return FeishuEvent(
        text=text,
        receive_id=receive_id,
        receive_id_type=receive_id_type,
        open_id=open_id,
        chat_id=chat_id,
    )


def extract_text_from_message(message: Any) -> str:
    if message is None:
        return ""
    content = getattr(message, "content", "")
    if not content:
        return ""
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            text = str(parsed.get("text", content)).strip()
        except json.JSONDecodeError:
            text = content.strip()
    elif isinstance(content, dict):
        text = str(content.get("text", "")).strip()
    else:
        text = str(content).strip()
    
    # Strip @mention prefix (Feishu format: "@_user_1 message" or "@bot_name message")
    import re
    text = re.sub(r"^@\S+\s*", "", text).strip()
    
    return text
