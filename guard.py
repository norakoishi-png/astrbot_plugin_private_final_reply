"""Request-local delivery guard. Does not change global tools or other sessions."""
import copy
from types import MethodType

ACTIVE = "_private_final_reply_active"
PENDING = "_private_final_reply_pending"
GUIDE = """[本轮文字发送协议]
普通文字聊天只输出一次最终回复，每个聊天气泡占一行，由平台分段发送。
send_message_to_user 仅用于图片、语音、视频和文件，不用于分条文字聊天。
若工具返回文字已暂存且尚未发送，请把要说的话放入最终回复，不重试发送工具。
不要先发送全文再分条重发，不向用户解释此内部协议。
"""


def plain_text_for_current_session(event, kwargs):
    current = event.unified_msg_origin
    if str(kwargs.get("session") or current) != current:
        return None
    messages = kwargs.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    if not all(isinstance(m, dict) and m.get("type") == "plain"
               and isinstance(m.get("text"), str) and m["text"].strip()
               for m in messages):
        return None
    return "\n".join(m["text"].strip() for m in messages)


def guard_request(event, req, allowed_sessions=()):
    if (event.unified_msg_origin not in allowed_sessions
            or ":FriendMessage:" not in event.unified_msg_origin):
        return False
    tools = getattr(req, "func_tool", None)
    if tools is None:
        return False
    original = tools.get_tool("send_message_to_user")
    if original is None or getattr(original, "_private_final_reply_guard", False):
        return False
    # Built-in tool uses call(), not handler. Leave unfamiliar plugin tools alone.
    if getattr(original, "handler", None) is not None:
        return False
    local_tools = copy.copy(tools)
    local_tools.tools = list(tools.tools)
    guarded = copy.copy(original)
    original_call = original.call

    async def call(_self, context, **kwargs):
        call_event = context.context.event
        # Never redirect an unrelated event even if a caller reuses this toolset.
        if call_event is event:
            text = plain_text_for_current_session(event, kwargs)
            if text is not None:
                pending = list(event.get_extra(PENDING, []) or [])
                if text not in pending:
                    pending.append(text)
                    event.set_extra(PENDING, pending)
                return ("Text queued locally; NOT SENT. Do not call this tool again "
                        "for this text. Output the chat text once in your final "
                        "response, one bubble per line; the platform will deliver it.")
        return await original_call(context, **kwargs)

    guarded.call = MethodType(call, guarded)
    guarded._private_final_reply_guard = True
    guarded.description = GUIDE + "\n" + original.description
    local_tools.add_tool(guarded)
    req.func_tool = local_tools
    event.set_extra(ACTIVE, True)
    if GUIDE not in (req.system_prompt or ""):
        req.system_prompt = (req.system_prompt or "") + "\n\n" + GUIDE
    return True


def fallback_text(event, response):
    if not event.get_extra(ACTIVE, False):
        return ""
    if getattr(response, "role", None) != "assistant":
        return ""
    if getattr(response, "tools_call_name", None):
        return ""
    if (getattr(response, "completion_text", "") or "").strip():
        return ""
    chain = getattr(response, "result_chain", None)
    if chain is not None and getattr(chain, "chain", None):
        return ""
    return "\n".join(event.get_extra(PENDING, []) or [])
