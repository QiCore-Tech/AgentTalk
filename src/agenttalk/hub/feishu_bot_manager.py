"""Multi-user Feishu bot manager with dynamic WebSocket connections."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from agenttalk.hub.store import HubStore
from agenttalk.feishu.worker import FeishuEventHandler, FeishuLongConnectionWorker, LarkMessenger
from agenttalk.feishu.service import FeishuAgentTalkService

logger = logging.getLogger(__name__)


class FeishuBotInstance:
    """Represents a single user's Feishu bot with WebSocket connection."""

    def __init__(self, bot_id: int, app_id: str, app_secret: str, handler: FeishuEventHandler):
        self.bot_id = bot_id
        self.app_id = app_id
        self.app_secret = app_secret
        self.handler = handler
        self.worker: FeishuLongConnectionWorker | None = None
        self.messenger: LarkMessenger | None = None

    def start(self) -> None:
        """Start the WebSocket connection."""
        self.worker = FeishuLongConnectionWorker(
            app_id=self.app_id,
            app_secret=self.app_secret,
            handler=self.handler,
        )
        self.worker.start_background()
        self.messenger = LarkMessenger(self.app_id, self.app_secret)
        logger.info("Feishu bot %s started", self.bot_id)

    def stop(self) -> None:
        """Stop the WebSocket connection."""
        # Note: FeishuLongConnectionWorker doesn't have a clean stop method yet
        logger.info("Feishu bot %s stop requested", self.bot_id)

    def send_to(self, destination_id: str, destination_type: str, message: str) -> None:
        """Send a message to a destination."""
        if not self.messenger:
            logger.warning("Bot %s messenger not initialized", self.bot_id)
            return

        from agenttalk.feishu.render import text_reply
        reply = text_reply(message)
        receive_id_type = "chat_id" if destination_type == "group" else "open_id"
        try:
            self.messenger.send_reply(destination_id, reply, receive_id_type=receive_id_type)
        except Exception as exc:
            logger.warning("Failed to send message via bot %s: %s", self.bot_id, exc)


class FeishuBotManager:
    """Manage multiple user Feishu bot instances."""

    def __init__(self, store: HubStore, feishu_service: FeishuAgentTalkService | None = None):
        self.store = store
        self.feishu_service = feishu_service
        self._bots: dict[int, FeishuBotInstance] = {}
        self._lock = threading.Lock()

    def register_bot(self, user_id: str, name: str, app_id: str, app_secret: str) -> int:
        """Register a new Feishu bot."""
        bot_id = self.store.create_feishu_bot(
            user_id=user_id,
            name=name,
            app_id=app_id,
            app_secret=app_secret,
        )

        # Start the bot immediately
        self._start_bot(bot_id, app_id, app_secret)
        return bot_id

    def _start_bot(self, bot_id: int, app_id: str, app_secret: str) -> None:
        """Start a single bot instance."""
        if bot_id in self._bots:
            return

        messenger = LarkMessenger(app_id, app_secret)
        # Create a handler for this bot with bot_id and store for private chat context
        if self.feishu_service:
            handler = FeishuEventHandler(
                self.feishu_service, messenger,
                bot_id=bot_id, store=self.store,
            )
        else:
            handler = FeishuEventHandler(
                FeishuAgentTalkService(self.store), messenger,
                bot_id=bot_id, store=self.store,
            )

        instance = FeishuBotInstance(bot_id, app_id, app_secret, handler)
        instance.start()

        with self._lock:
            self._bots[bot_id] = instance

    def send_notification(
        self,
        agent_short_id: str,
        event_type: str,
        message: str,
    ) -> list[tuple[int, str]]:
        """Send notification according to routing rules. Returns list of (bot_id, status)."""
        routes = self.store.list_notification_routes(
            agent_short_id=agent_short_id,
            event_type=event_type,
        )

        results: list[tuple[int, str]] = []
        for route in routes:
            if not route.get("enabled"):
                continue

            bot_id = route["feishu_bot_id"]
            bot = self._bots.get(bot_id)

            if not bot:
                # Try to start the bot if not running
                bot_info = self.store.get_feishu_bot(bot_id)
                if bot_info:
                    self._start_bot(bot_id, bot_info["app_id"], bot_info["app_secret"])
                    bot = self._bots.get(bot_id)

            if bot:
                try:
                    bot.send_to(
                        route["destination_id"],
                        route["destination_type"],
                        message,
                    )
                    results.append((bot_id, "sent"))
                except Exception as exc:
                    logger.warning("Failed to send notification via bot %s: %s", bot_id, exc)
                    results.append((bot_id, f"failed: {exc}"))
            else:
                results.append((bot_id, "bot_not_found"))

        return results

    def get_bot_status(self, bot_id: int) -> dict[str, Any]:
        """Get status of a bot."""
        bot = self._bots.get(bot_id)
        info = self.store.get_feishu_bot(bot_id)
        return {
            "bot_id": bot_id,
            "registered": info is not None,
            "running": bot is not None,
            "status": info.get("status") if info else "unknown",
        }

    def stop_all(self) -> None:
        """Stop all bot instances."""
        for bot in self._bots.values():
            bot.stop()
        self._bots.clear()
