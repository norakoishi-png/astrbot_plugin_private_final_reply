import asyncio
import sys
import unittest
from types import SimpleNamespace as NS
from guard import PENDING, guard_request, fallback_text

TARGET = "test-bot:FriendMessage:test-user"


class Event:
    def __init__(self, session=TARGET):
        self.unified_msg_origin = session
        self.extra = {}
    def get_extra(self, key, default=None):
        return self.extra.get(key, default)
    def set_extra(self, key, value):
        self.extra[key] = value


class Sender:
    name = "send_message_to_user"
    description = "Send media or text"
    handler = None
    def __init__(self):
        self.sent = []
    async def call(self, context, **kwargs):
        self.sent.append(kwargs)
        return "sent"


class ToolSet:
    def __init__(self, tool): self.tools = [tool]
    def get_tool(self, name):
        return next((t for t in self.tools if t.name == name), None)
    def add_tool(self, tool):
        self.tools = [tool if t.name == tool.name else t for t in self.tools]


class GuardTests(unittest.IsolatedAsyncioTestCase):
    def setup_request(self, session=TARGET):
        event = Event(session)
        original = Sender()
        req = NS(func_tool=ToolSet(original), system_prompt="unchanged persona")
        shared = req.func_tool
        if "--baseline" not in sys.argv:
            guard_request(event, req, [TARGET])
        return event, original, req, shared

    async def test_logged_paraphrase_and_repeated_tool_call_sent_once(self):
        event, sender, req, shared = self.setup_request()
        ctx = NS(context=NS(event=event))
        # Regression pattern: tool body, then slightly different final body.
        args = {"messages": [{"type":"plain", "text":"今天收拾了屋子"},
                             {"type":"plain", "text":"也翻了两页书"}]}
        tool = req.func_tool.get_tool("send_message_to_user")
        await tool.call(ctx, **args)
        await tool.call(ctx, **args)
        self.assertEqual(sender.sent, [], "chat text was prematurely delivered via tool")
        self.assertEqual(len(event.get_extra(PENDING)), 1)
        self.assertIs(shared.get_tool("send_message_to_user"), sender)
        self.assertFalse(hasattr(sender, "_private_final_reply_guard"))
        final = NS(role="assistant", completion_text="今天收拾了一下屋子\n也翻了两页书", tools_call_name=[], result_chain=None)
        self.assertEqual(fallback_text(event, final), "")

    async def test_media_mixed_and_cross_session_keep_original_sender(self):
        event, sender, req, _ = self.setup_request()
        ctx = NS(context=NS(event=event))
        tool = req.func_tool.get_tool("send_message_to_user")
        for messages in ([{"type":"image","url":"https://example.invalid/image"}],
                         [{"type":"record","path":"voice.wav"}],
                         [{"type":"plain","text":"说明"},{"type":"image","path":"image.png"}]):
            await tool.call(ctx, messages=messages)
        await tool.call(ctx, messages=[{"type":"plain","text":"other"}], session="test-bot:GroupMessage:test-group")
        self.assertEqual(len(sender.sent), 4)

    async def test_empty_allowlist_is_noop(self):
        event = Event()
        req = NS(func_tool=ToolSet(Sender()), system_prompt="original")
        shared = req.func_tool
        self.assertFalse(guard_request(event, req))
        self.assertIs(req.func_tool, shared)
        self.assertEqual(req.system_prompt, "original")

    async def test_other_sessions_unchanged(self):
        event, sender, req, shared = self.setup_request("test-bot:GroupMessage:test-group")
        self.assertIs(req.func_tool, shared)
        self.assertEqual(req.system_prompt, "unchanged persona")
        await req.func_tool.get_tool(sender.name).call(NS(context=NS(event=event)), messages=[{"type":"plain","text":"normal"}])
        self.assertEqual(len(sender.sent), 1)

    async def test_empty_final_recovers_queued_text_without_sending(self):
        event, sender, req, _ = self.setup_request()
        await req.func_tool.get_tool(sender.name).call(NS(context=NS(event=event)), messages=[{"type":"plain","text":"第一句"},{"type":"plain","text":"第二句"}])
        response = NS(role="assistant", completion_text="", result_chain=None, tools_call_name=[])
        self.assertEqual(fallback_text(event, response), "第一句\n第二句")
        response.tools_call_name = ["some_other_tool"]
        self.assertEqual(fallback_text(event, response), "")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
