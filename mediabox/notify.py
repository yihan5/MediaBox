"""Telegram 通知。只发消息、不收消息，所以和 dsh 共用同一个 bot 也不会冲突。

通知失败只记日志，绝不影响下载本身。
"""

from __future__ import annotations

import json
import logging
import urllib.request

from .config import TelegramConfig

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg: TelegramConfig):
        self.cfg = cfg

    def send(self, text: str) -> None:
        if not self.cfg.enabled:
            log.info("（未配置 Telegram，跳过通知）%s", text)
            return
        url = f"https://api.telegram.org/bot{self.cfg.bot_token}/sendMessage"
        body = json.dumps(
            {"chat_id": self.cfg.chat_id, "text": text, "disable_web_page_preview": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
        except Exception as e:  # noqa: BLE001 —— 通知失败不能拖垮下载
            log.warning("Telegram 通知发送失败：%s", e)
