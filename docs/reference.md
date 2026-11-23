# 接口与配置参考

[返回首页](../README.md)

## HTTP 接口

所有接口都只监听 `127.0.0.1`。除了 `/api/health`，都需要在请求头里带 `X-API-Key`。

### `POST /api/links`：提交链接

请求：

```json
{ "url": "【标题-哔哩哔哩】 https://b23.tv/AbCdEf" }
```

`url` 可以是一个单纯的链接，也可以是一整段分享文字。程序会取出其中的第一个链接。

响应：通过鉴权和参数校验后，以下三种业务结果的 HTTP 状态码都是 200，结果写在 `result` 字段里。

```json
{
  "result": "accepted",
  "message": "已加入：《xxx》（12分30秒）。今天已用 57/90 分钟，3/5 个。",
  "item": {
    "id": 42, "platform": "bilibili", "video_id": "BV1xx411c7mD",
    "title": "xxx", "duration": 750, "duration_minutes": 12.5,
    "media_day": "2026-11-22", "status": "queued", "...": "..."
  },
  "quota": {
    "used_minutes": 57, "limit_minutes": 90, "remaining_minutes": 33,
    "used_count": 3, "limit_count": 5, "remaining_count": 2
  }
}
```

| `result` | 含义 |
|---|---|
| `accepted` | 已加入队列 |
| `rejected` | 被拒绝：额度用完、不支持的网站、直播、合集、解析失败等。原因写在 `message` 里 |
| `duplicate` | 这个视频已经下载过或正在排队，不扣额度 |

### `GET /api/status`：查询状态

```json
{
  "media_day": "2026-11-22",
  "day_starts_at_hour": 2,
  "quota": { "...": "同上" },
  "summary": "今天已用 57/90 分钟，3/5 个",
  "today": [ { "...": "今天的所有记录" } ],
  "pending": [ { "...": "所有排队中或下载中的，包括之前几天的" } ],
  "recent_failures": [ { "...": "最近 10 条失败记录，含 error 字段" } ]
}
```

### `GET /api/health`：健康检查

不需要密钥，只返回 `{"ok": true}`，可以用来检查服务在不在运行。

### 错误

- `401`：没有带密钥，或者密钥不对。
- `422`：请求体格式不对，比如缺少 `url` 字段。

<a id="settings"></a>

## 配置项

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `[server] host` | `"127.0.0.1"` | 监听地址。不要改成 `0.0.0.0` |
| `[server] port` | `8765` | 端口 |
| `[server] api_key` | 无 | **必填**。用默认值 `change-me` 的话程序不会启动 |
| `[paths] media_root` | `'D:\Share'` | 视频存放的根目录 |
| `[paths] data_dir` | `'data'` | 数据库和日志的位置 |
| `[paths] bilibili_cookies` | `'cookies\bilibili.txt'` | B 站 cookie 文件。文件不存在也能运行，但可选清晰度可能受限 |
| `[paths] youtube_cookies` | `""` | YouTube cookie，一般不用 |
| `[paths] extra_bin_dirs` | `[]` | 程序启动时会把这些文件夹加到 PATH 里，用来让服务找到 ffmpeg 和 deno |
| `[quota] daily_minutes` | `90` | 提交时检查的已用时长门槛（分钟），允许最后一个视频透支 |
| `[quota] daily_count` | `5` | 每天最多几个 |
| `[quota] day_starts_at_hour` | `2` | 一天从几点开始算（0~23） |
| `[download] max_height` | `1080` | 最高分辨率 |
| `[download] prefer_h264` | `false` | 设为 `true` 时优先下载 H.264 编码：所有设备都能硬件解码、更省电，但文件更大 |
| `[download] subtitle_langs` | `["zh.*", "en.*"]` | 字幕语言，支持正则表达式。只下载人工字幕 |
| `[download] rate_limit` | `""` | 下载限速，比如 `"5M"`。留空表示不限速 |
| `[download] title_max_bytes` | `120` | 文件名里的标题最多占多少字节（一个中文字约 3 字节） |
| `[download] bilibili_min_expected_height` | `720` | B 站画质低于这个值时，提醒你检查 cookie |
| `[telegram] bot_token` | `""` | bot 的 token |
| `[telegram] chat_id` | `""` | 你的用户 ID |

改完配置后都要运行 `nssm restart MediaBox` 才会生效。配置写错的话服务会启动失败，原因会写在 `data\logs\service-stderr.log` 里。
