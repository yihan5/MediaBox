"""HTTP 接口（FastAPI）。只做三件事：校验密钥、把请求交给 MediaService、返回 JSON。

接口：
    GET  /             本机管理页面
    POST /api/links    提交链接        需要请求头 X-API-Key
    GET  /api/status   今天的额度和列表  需要请求头 X-API-Key
    GET  /api/health   健康检查（不需要密钥，只返回 ok）
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import Config
from .db import Database
from .downloader import Downloader
from .notify import Notifier
from .service import MediaService
from .worker import DownloadWorker

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


class LinkIn(BaseModel):
    # 可以只是一个链接，也可以是 B 站分享出来的一整段文字，程序会自己找出链接
    url: str


def create_app(cfg: Config) -> FastAPI:
    db = Database(cfg.paths.data_dir / "mediabox.db")
    downloader = Downloader(cfg)
    notifier = Notifier(cfg.telegram)
    worker = DownloadWorker(cfg, db, downloader, notifier)
    service = MediaService(cfg, db, probe=downloader.probe, wake_worker=worker.wake)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker.start()
        log.info("MediaBox 已启动：http://%s:%s", cfg.server.host, cfg.server.port)
        yield
        worker.stop()

    app = FastAPI(title="MediaBox", lifespan=lifespan, docs_url=None, redoc_url=None)

    def require_key(x_api_key: str | None = Header(default=None)) -> None:
        # compare_digest：比较时间不随内容变化，避免被逐字猜出密钥
        if not x_api_key or not hmac.compare_digest(x_api_key, cfg.server.api_key):
            raise HTTPException(status_code=401, detail="密钥不对或没有提供（请求头 X-API-Key）。")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/api/health")
    def health():
        return {"ok": True}

    # 注意：这两个是普通 def（不是 async def），FastAPI 会把它们放到线程池里运行，
    # 解析链接要联网几秒钟，不会卡住其他请求。
    @app.post("/api/links", dependencies=[Depends(require_key)])
    def submit_link(body: LinkIn):
        return service.submit(body.url).to_dict()

    @app.get("/api/status", dependencies=[Depends(require_key)])
    def status():
        return service.status()

    return app
