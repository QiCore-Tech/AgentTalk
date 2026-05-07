from __future__ import annotations

from dataclasses import dataclass, field

from agenttalk.feishu.render import FeishuReply
from agenttalk.feishu.worker import FeishuEvent, FeishuEventHandler, extract_event, extract_text_from_message


class FakeService:
    def __init__(self) -> None:
        self.handled: list[tuple[str, str, str]] = []

    def handle(self, command, operator):  # noqa: ANN001
        self.handled.append((command.raw, operator.open_id, operator.chat_id))
        return FeishuReply("text", "ok")


class FakeMessenger:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, FeishuReply]] = []

    def send_reply(self, receive_id: str, reply: FeishuReply, *, receive_id_type: str = "chat_id") -> None:
        self.sent.append((receive_id, receive_id_type, reply))


def test_event_handler_sends_reply() -> None:
    service = FakeService()
    messenger = FakeMessenger()
    handler = FeishuEventHandler(service, messenger)  # type: ignore[arg-type]

    reply = handler.handle_event(FeishuEvent(text="/help", receive_id="oc_123", open_id="ou_123", chat_id="oc_123"))

    assert reply.content == "ok"
    assert service.handled == [("/help", "ou_123", "oc_123")]
    assert messenger.sent == [("oc_123", "chat_id", FeishuReply("text", "ok"))]


def test_extract_text_from_json_message_content() -> None:
    @dataclass
    class Message:
        content: str = '{"text":"/agents"}'

    assert extract_text_from_message(Message()) == "/agents"


def test_extract_event_from_sdk_like_object() -> None:
    @dataclass
    class SenderId:
        open_id: str = "ou_123"

    @dataclass
    class Sender:
        sender_id: SenderId = field(default_factory=SenderId)

    @dataclass
    class Message:
        chat_id: str = "oc_123"
        content: str = '{"text":"/agents"}'

    @dataclass
    class InnerEvent:
        message: Message = field(default_factory=Message)
        sender: Sender = field(default_factory=Sender)

    @dataclass
    class EventWrapper:
        event: InnerEvent = field(default_factory=InnerEvent)

    event = extract_event(EventWrapper())

    assert event.text == "/agents"
    assert event.receive_id == "oc_123"
    assert event.receive_id_type == "chat_id"
    assert event.chat_id == "oc_123"
    assert event.open_id == "ou_123"


def test_extract_event_falls_back_to_open_id_receive_type() -> None:
    @dataclass
    class SenderId:
        open_id: str = "ou_123"

    @dataclass
    class Sender:
        sender_id: SenderId = field(default_factory=SenderId)

    @dataclass
    class Message:
        content: str = '{"text":"/agents"}'

    @dataclass
    class InnerEvent:
        message: Message = field(default_factory=Message)
        sender: Sender = field(default_factory=Sender)

    @dataclass
    class EventWrapper:
        event: InnerEvent = field(default_factory=InnerEvent)

    event = extract_event(EventWrapper())

    assert event.receive_id == "ou_123"
    assert event.receive_id_type == "open_id"
