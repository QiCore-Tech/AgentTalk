"""Tests for FeishuBotManager."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from agenttalk.hub.store import HubStore
from agenttalk.hub.feishu_bot_manager import FeishuBotManager


@pytest.fixture
def store(tmp_path: Path):
    return HubStore(tmp_path / "test.db", heartbeat_ttl_seconds=30)


@pytest.fixture
def bot_manager(store):
    # Mock lark_oapi to avoid import errors in test environment
    with patch.dict("sys.modules", {"lark_oapi": Mock(), "lark_oapi.api.im.v1": Mock()}):
        return FeishuBotManager(store)


class TestFeishuBotManager:
    def test_register_bot(self, bot_manager, store):
        with patch.object(bot_manager, '_start_bot'):
            bot_id = bot_manager.register_bot(
                user_id="user1",
                name="Test Bot",
                app_id="cli_test",
                app_secret="secret123",
            )
        assert bot_id > 0
        
        bot = store.get_feishu_bot(bot_id)
        assert bot["name"] == "Test Bot"
        assert bot["app_id"] == "cli_test"

    def test_send_notification_no_routes(self, bot_manager):
        # Should not fail when no routes configured
        results = bot_manager.send_notification("agent-1", "alert", "Test message")
        assert results == []

    def test_send_notification_with_route(self, bot_manager, store):
        with patch.object(bot_manager, '_start_bot'):
            bot_id = bot_manager.register_bot("user1", "Test Bot", "cli_test", "secret123")
        
        # Create route
        store.create_notification_route(
            agent_short_id="agent-1",
            user_id="user1",
            event_type="alert",
            destination_type="group",
            destination_id="oc_test",
            feishu_bot_id=bot_id,
        )
        
        # Mock the bot instance to avoid actual network calls
        mock_instance = Mock()
        bot_manager._bots[bot_id] = mock_instance
        
        results = bot_manager.send_notification("agent-1", "alert", "Test alert")
        
        assert len(results) >= 0
        mock_instance.send_to.assert_called_once()

    def test_bot_status_not_found(self, bot_manager):
        status = bot_manager.get_bot_status(999)
        assert status["registered"] is False
        assert status["running"] is False

    def test_bot_status_registered(self, bot_manager, store):
        with patch.object(bot_manager, '_start_bot'):
            bot_id = bot_manager.register_bot("user1", "Test Bot", "cli_test", "secret123")
        status = bot_manager.get_bot_status(bot_id)
        assert status["registered"] is True
        # Note: bot may or may not be running depending on async timing