"""Manual Slack routing and shared prompt, without importing live app services."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import briefing


class FakeApp:
    def __init__(self, **kwargs):
        pass

    def event(self, name):
        return lambda function: function


def fake_module(name, **attributes):
    module = ModuleType(name)
    module.__dict__.update(attributes)
    return module


def load_app():
    cfg = SimpleNamespace(voice_mode="off", voice_name="test", voice_max_chars=100,
                          slack_bot_token="fake", pakuri_path="C:/fake-pakuri")
    brain = SimpleNamespace(ask=AsyncMock(return_value="Ordinary answer"))
    voice = SimpleNamespace(speak=AsyncMock())
    mocks = {
        "net": fake_module("net"),
        "slack_bolt": fake_module("slack_bolt"),
        "slack_bolt.adapter": fake_module("slack_bolt.adapter"),
        "slack_bolt.adapter.socket_mode": fake_module("slack_bolt.adapter.socket_mode"),
        "slack_bolt.adapter.socket_mode.async_handler": fake_module(
            "slack_bolt.adapter.socket_mode.async_handler", AsyncSocketModeHandler=object),
        "slack_bolt.async_app": fake_module("slack_bolt.async_app", AsyncApp=FakeApp),
        "brain": fake_module("brain", Brain=lambda config: brain),
        "cli": fake_module("cli", ensure_claude_on_path=lambda: None),
        "config": fake_module("config", load_config=lambda: cfg),
        "owner": fake_module("owner", save_owner=lambda *args: None),
        "voice": fake_module("voice", Voice=lambda *args: voice),
    }
    path = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("manual_briefing_test_app", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, mocks):
        spec.loader.exec_module(module)
    return module


class RequestTests(unittest.TestCase):
    def test_direct_commands_and_conversations_stay_separate(self):
        yes = ("브리핑", "브리핑 해줘", "오늘 브리핑 해줘", "아침 브리핑 부탁해",
               "오늘의 브리핑 보여줘!", "브리핑 좀 해줘", "오늘 아침 브리핑 부탁해",
               "브리핑 해줄래?", "brief me", "daily briefing", "Please brief me")
        no = ("브리핑 시간 바꿔줘", "브리핑 설정", "브리핑 중단해줘", "브리핑이 뭐야?",
              "'브리핑 해줘'라고 말하면 돼?", "`브리핑`", "오늘 브리핑 잘 봤어",
              "daily briefing schedule", "What is a daily briefing?", "AI 동향 이야기해줘")
        for value in yes + no:
            with self.subTest(value=value):
                self.assertEqual(briefing.is_briefing_request(value), value in yes)


class ManualTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = load_app()
        self.client = SimpleNamespace(reactions_add=AsyncMock(), reactions_remove=AsyncMock(),
                                      chat_postMessage=AsyncMock(return_value={"ok": True}))

    async def test_shared_generator_prefetches_manual_and_preserves_source_links(self):
        news = {"ai": {"items": [{"url": "https://example.test/release", "published_at": "2026-10-01"}]}}
        offered = [{"key": "ai:example", "url": "https://example.test/release"}]
        brain = SimpleNamespace(ask=AsyncMock(return_value="Briefing"))
        cfg = object()
        instant = datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)
        with patch.object(briefing, "prepare_trends", AsyncMock(return_value=(news, offered))) as prepare, \
                patch.object(briefing, "datetime") as clock:
            clock.now.side_effect = lambda tz: instant.astimezone(tz)
            reply, actual = await briefing.generate_briefing(brain, cfg, key="DM", manual=True, request="브리핑 해줘")
        prepare.assert_awaited_once_with(cfg, include_delivered=True)
        self.assertEqual((reply, actual), ("Briefing", offered))
        key, prompt = brain.ask.await_args.args
        self.assertEqual(key, "DM")
        self.assertIn("https://example.test/release", prompt)
        self.assertIn("2026-10-01", prompt)
        self.assertIn("오늘 날짜(Asia/Seoul): 2026-10-01", prompt)
        self.assertIn("<https://...|원문>", prompt)
        self.assertIn("pakuri_activity 도구를 호출하지 마", prompt)

    async def test_threaded_request_delivers_one_combined_nonconsuming_message(self):
        event = {"text": "<@UFAKE> 오늘 브리핑 해줘", "channel": "CFAKE", "ts": "2", "thread_ts": "1"}
        offered = [{"key": "ai:test", "url": "https://example.test"}]
        with patch.object(self.app, "generate_briefing", AsyncMock(return_value=("Combined briefing", offered))) as generate, \
                patch.object(self.app, "deliver_briefing", AsyncMock()) as deliver:
            await self.app._process(event, self.client)
        generate.assert_awaited_once_with(self.app.brain, self.app.config, key="CFAKE:1", manual=True,
                                         request="오늘 브리핑 해줘")
        deliver.assert_awaited_once_with(self.client, channel="CFAKE", thread_ts="1", text="Combined briefing",
                                        offered=offered, project_path=self.app.config.pakuri_path, consume=False)
        self.client.chat_postMessage.assert_not_awaited()
        self.app.brain.ask.assert_not_awaited()
        self.client.reactions_remove.assert_awaited_once()

    async def test_normal_conversation_retains_existing_route(self):
        with patch.object(self.app, "generate_briefing", AsyncMock()) as generate, \
                patch.object(self.app, "deliver_briefing", AsyncMock()) as deliver:
            await self.app._process({"text": "브리핑 시간 바꿔줘", "channel": "DFAKE", "ts": "2"}, self.client)
        self.app.brain.ask.assert_awaited_once_with("DFAKE", "브리핑 시간 바꿔줘")
        self.client.chat_postMessage.assert_awaited_once_with(channel="DFAKE", thread_ts=None, text="Ordinary answer")
        generate.assert_not_awaited()
        deliver.assert_not_awaited()

    async def test_failed_generation_keeps_single_existing_error_reply(self):
        with patch.object(self.app, "generate_briefing", AsyncMock(side_effect=RuntimeError("fixture generation error"))), \
                patch.object(self.app, "deliver_briefing", AsyncMock()) as deliver:
            await self.app._process({"text": "brief me", "channel": "DFAKE", "ts": "2"}, self.client)
        deliver.assert_not_awaited()
        self.client.chat_postMessage.assert_awaited_once()
        self.assertIn("fixture generation error", self.client.chat_postMessage.await_args.kwargs["text"])
        self.client.reactions_remove.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
