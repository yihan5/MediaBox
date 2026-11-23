"""SQLite 存储。一张 items 表同时充当「下载记录」和「下载队列」。

状态流转：
    queued（排队中）-> downloading（下载中）-> done（完成）
                                             -> failed（失败，不计入额度）

每次操作都新开一个连接：SQLite 连接不能跨线程共用，
而这里有两个线程（接口线程 + 下载线程）。新开连接的开销很小，换来的是简单和安全。
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    platform      TEXT    NOT NULL,          -- bilibili / youtube
    video_id      TEXT    NOT NULL,          -- 平台上的视频 ID，用来去重
    url           TEXT    NOT NULL,          -- 你提交的原始链接
    webpage_url   TEXT,                      -- yt-dlp 解析出的规范链接
    title         TEXT,
    uploader      TEXT,
    duration      INTEGER NOT NULL,          -- 秒
    media_day     TEXT    NOT NULL,          -- 属于哪一天（按凌晨 2 点切分），YYYY-MM-DD
    status        TEXT    NOT NULL,          -- queued / downloading / done / failed
    error         TEXT,
    file_path     TEXT,
    height        INTEGER,                   -- 实际下载到的分辨率高度
    created_at    TEXT    NOT NULL,          -- 提交时间（本地时间 ISO 格式）
    started_at    TEXT,
    finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_day    ON items(media_day);
CREATE INDEX IF NOT EXISTS idx_items_video  ON items(platform, video_id);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
"""

# 提交链接时「查重 + 查额度 + 写入」必须是一个整体，否则两个同时到达的请求
# 可能都看到「还剩 1 个名额」然后都被放行。用一把进程内的锁保证这一点。
submit_lock = threading.Lock()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------------- 查询 ----------------

    def find_active_duplicate(self, platform: str, video_id: str) -> sqlite3.Row | None:
        """同一个视频只要有过非失败的记录（排队/下载中/已完成），就算重复。
        失败的记录不算：失败后可以重新提交。"""
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM items WHERE platform=? AND video_id=? AND status!='failed' "
                "ORDER BY id DESC LIMIT 1",
                (platform, video_id),
            ).fetchone()

    def usage_for_day(self, day: date) -> tuple[int, int]:
        """返回 (已用秒数, 已用个数)，不含失败的记录。"""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(duration),0) AS s, COUNT(*) AS c FROM items "
                "WHERE media_day=? AND status!='failed'",
                (day.isoformat(),),
            ).fetchone()
            return int(row["s"]), int(row["c"])

    def items_for_day(self, day: date) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM items WHERE media_day=? ORDER BY id", (day.isoformat(),)
            ).fetchall()

    def pending_items(self) -> list[sqlite3.Row]:
        """所有还没处理完的（可能包括前几天留下的）。"""
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM items WHERE status IN ('queued','downloading') ORDER BY id"
            ).fetchall()

    def recent_failures(self, limit: int = 10) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM items WHERE status='failed' ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def get(self, item_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()

    # ---------------- 写入 ----------------

    def insert_item(
        self,
        *,
        platform: str,
        video_id: str,
        url: str,
        webpage_url: str | None,
        title: str | None,
        uploader: str | None,
        duration: int,
        media_day: date,
        created_at: datetime,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO items (platform, video_id, url, webpage_url, title, uploader, "
                "duration, media_day, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?, 'queued', ?)",
                (
                    platform, video_id, url, webpage_url, title, uploader,
                    duration, media_day.isoformat(), created_at.isoformat(timespec="seconds"),
                ),
            )
            return int(cur.lastrowid)

    def claim_next(self) -> sqlite3.Row | None:
        """取出最早的一条 queued，并标记为 downloading。只有下载线程会调用。"""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM items WHERE status='queued' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE items SET status='downloading', started_at=? WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"), row["id"]),
            )
            return conn.execute("SELECT * FROM items WHERE id=?", (row["id"],)).fetchone()

    def mark_done(self, item_id: int, file_path: str | None, height: int | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE items SET status='done', file_path=?, height=?, error=NULL, finished_at=? "
                "WHERE id=?",
                (file_path, height, datetime.now().isoformat(timespec="seconds"), item_id),
            )

    def mark_failed(self, item_id: int, error: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE items SET status='failed', error=?, finished_at=? WHERE id=?",
                (error[:2000], datetime.now().isoformat(timespec="seconds"), item_id),
            )

    def requeue_interrupted(self) -> int:
        """程序启动时调用：上次崩溃或关机时正在下载的，重新排队。"""
        with self.connect() as conn:
            cur = conn.execute("UPDATE items SET status='queued' WHERE status='downloading'")
            return cur.rowcount


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["duration_minutes"] = round((d.get("duration") or 0) / 60, 1)
    return d
