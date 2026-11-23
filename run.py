"""启动入口：python run.py

手动运行和作为 Windows 服务运行用的都是这个文件。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from mediabox.config import ConfigError, apply_extra_bin_dirs, load_config


def setup_logging(log_dir) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # 日志文件：最多 5 个 × 2 MB，自动轮换，不会无限变大
    fh = RotatingFileHandler(
        log_dir / "mediabox.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # yt-dlp 的普通输出走 debug 级别，这里只保留警告和错误
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)


def main() -> None:
    # Windows 控制台默认编码可能不是 UTF-8，避免中文标题打印时报错
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"[配置错误] {e}", file=sys.stderr)
        sys.exit(1)

    setup_logging(cfg.paths.data_dir / "logs")
    apply_extra_bin_dirs(cfg)

    import uvicorn

    from mediabox.app import create_app

    app = create_app(cfg)
    # log_config=None：让 uvicorn 用我们上面配置好的日志，而不是它自己的
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_config=None)


if __name__ == "__main__":
    main()
