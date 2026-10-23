from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.provider import ProviderRequest, LLMResponse
from astrbot.api.star import Context, Star, register
from .guard import guard_request, fallback_text


@register("private_final_reply", "norakoishi-png", "指定私聊文字统一最终分段发送", "1.1.0")
class PrivateFinalReply(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        logger.info("[Private Final Reply] loaded; scoped private text delivery only")

    @filter.on_llm_request(priority=-2000)
    async def prepare(self, event: AstrMessageEvent, req: ProviderRequest):
        if self.config.get("enabled", True) and guard_request(
            event, req, self.config.get("sessions", [])
        ):
            logger.info("[Private Final Reply] request-local text guard installed")

    @filter.on_llm_response(priority=-2000)
    async def restore_empty_final(self, event: AstrMessageEvent, resp: LLMResponse):
        text = fallback_text(event, resp)
        if text:
            resp.completion_text = text
            logger.info("[Private Final Reply] restored queued text into empty final response")
