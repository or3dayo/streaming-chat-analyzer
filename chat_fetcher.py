"""アーカイブ動画からチャットを取得する。

- YouTube: yt-dlp の live_chat 字幕をパース
- Twitch: 公式 GraphQL API を直接叩く(VideoCommentsByOffsetOrCursor)
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable

import requests
import yt_dlp


@dataclass
class ChatMessage:
    time_seconds: float
    author: str
    text: str


def fetch_chat(
    url: str,
    progress_cb: Callable[[int], None] | None = None,
) -> list[ChatMessage]:
    if "twitch.tv" in url:
        return _fetch_twitch(url, progress_cb)
    return _fetch_youtube(url, progress_cb)


def fetch_chat_from_json_text(
    raw_text: str,
    progress_cb: Callable[[int], None] | None = None,
) -> list[ChatMessage]:
    """TwitchDownloaderCLI 等で生成した chat.json の中身(文字列)を読み込む。"""
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(raw_text)
        tmp_path = tmp.name

    try:
        messages = _parse_twitch_chat_file(tmp_path, progress_cb)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if progress_cb:
        progress_cb(len(messages))
    return messages


# ========== YouTube ==========

def _fetch_youtube(
    url: str, progress_cb: Callable[[int], None] | None
) -> list[ChatMessage]:
    with tempfile.TemporaryDirectory() as tmpdir:
        outtmpl = os.path.join(tmpdir, "%(id)s.%(ext)s")
        ydl_opts = {
            "skip_download": True,
            "writesubtitles": True,
            "subtitleslangs": ["live_chat"],
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            raise RuntimeError(f"yt-dlp取得失敗: {e}") from e

        video_id = info.get("id", "")
        chat_path = None
        for fname in os.listdir(tmpdir):
            if fname.startswith(video_id) and fname.endswith(".json"):
                chat_path = os.path.join(tmpdir, fname)
                break

        if not chat_path:
            raise RuntimeError(
                "チャットファイルが見つかりません。チャットリプレイ無効の配信の可能性があります。"
            )

        messages = _parse_youtube_live_chat(chat_path, progress_cb)

    if progress_cb:
        progress_cb(len(messages))
    return messages


def _parse_youtube_live_chat(
    path: str, progress_cb: Callable[[int], None] | None
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            replay = obj.get("replayChatItemAction")
            if not replay:
                continue
            offset_ms = replay.get("videoOffsetTimeMsec")
            if offset_ms is None:
                continue
            time_sec = float(offset_ms) / 1000.0

            for action in replay.get("actions", []):
                msg = _extract_youtube_message(action, time_sec)
                if msg:
                    messages.append(msg)
                    if progress_cb and len(messages) % 200 == 0:
                        progress_cb(len(messages))
    return messages


def _extract_youtube_message(action: dict, time_sec: float) -> ChatMessage | None:
    add = action.get("addChatItemAction")
    if not add:
        return None
    item = add.get("item", {})
    renderer = (
        item.get("liveChatTextMessageRenderer")
        or item.get("liveChatPaidMessageRenderer")
        or item.get("liveChatMembershipItemRenderer")
    )
    if not renderer:
        return None

    text_parts: list[str] = []
    for run in renderer.get("message", {}).get("runs", []):
        if "text" in run:
            text_parts.append(run["text"])
        elif "emoji" in run:
            shortcuts = run["emoji"].get("shortcuts") or []
            if shortcuts:
                text_parts.append(shortcuts[0])
    text = "".join(text_parts).strip()
    if not text:
        return None

    author = (renderer.get("authorName") or {}).get("simpleText") or "anonymous"
    return ChatMessage(time_sec, author, text)


# ========== Twitch ==========

# Twitch公式Webクライアントの公開Client-ID(認証不要のpublic ID)
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
TWITCH_GQL_URL = "https://gql.twitch.tv/gql"
TWITCH_INTEGRITY_URL = "https://gql.twitch.tv/integrity"
# VideoCommentsByOffsetOrCursor の persisted query hash(Twitch公開GraphQLで安定使用)
TWITCH_PERSISTED_HASH = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _extract_twitch_video_id(url: str) -> str:
    m = re.search(r"twitch\.tv/videos/(\d+)", url)
    if not m:
        raise RuntimeError(
            "Twitch VOD URLが認識できません。例: https://www.twitch.tv/videos/123456789"
        )
    return m.group(1)


def _fetch_twitch(
    url: str, progress_cb: Callable[[int], None] | None
) -> list[ChatMessage]:
    """yt-dlp で Twitch のチャットリプレイ字幕を取得してパース。"""
    _extract_twitch_video_id(url)  # URL形式検証のみ

    with tempfile.TemporaryDirectory() as tmpdir:
        outtmpl = os.path.join(tmpdir, "%(id)s.%(ext)s")
        ydl_opts = {
            "skip_download": True,
            "writesubtitles": True,
            "subtitleslangs": ["rechat", "live_chat"],
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            raise RuntimeError(
                f"yt-dlp Twitch取得失敗: {e}\n"
                "回避策: TwitchDownloaderCLIでchat.jsonを作って取り込む方式があります。"
            ) from e

        chat_path = None
        for fname in os.listdir(tmpdir):
            if fname.endswith(".json"):
                chat_path = os.path.join(tmpdir, fname)
                break

        if not chat_path:
            raise RuntimeError(
                "Twitchチャットファイルが見つかりません(VOD削除済み/限定公開/チャット非保持の可能性)。"
            )

        messages = _parse_twitch_chat_file(chat_path, progress_cb)

    if progress_cb:
        progress_cb(len(messages))
    return messages


def _parse_twitch_chat_file(
    path: str, progress_cb: Callable[[int], None] | None
) -> list[ChatMessage]:
    """yt-dlp / TwitchDownloaderCLI / chat-downloader 等の複数フォーマットに対応した
    Twitchチャットパーサ。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    # JSON配列 or 単一オブジェクト形式
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # JSONL(1行1JSON)形式
        data = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # トップレベルが dict なら comments 配列を探す
    if isinstance(data, dict):
        if "comments" in data:
            data = data["comments"]
        elif "video" in data and isinstance(data["video"], dict):
            data = data["video"].get("comments", [])

    if not isinstance(data, list):
        raise RuntimeError(f"想定外のTwitchチャットJSON形式: {type(data).__name__}")

    messages: list[ChatMessage] = []
    for item in data:
        msg = _extract_twitch_message_any(item)
        if msg:
            messages.append(msg)
            if progress_cb and len(messages) % 200 == 0:
                progress_cb(len(messages))
    return messages


def _extract_twitch_message_any(item: dict) -> ChatMessage | None:
    """Twitchチャットの様々な形式からChatMessage化を試みる。"""
    if not isinstance(item, dict):
        return None

    # 形式1: TwitchDownloaderCLI / 旧v5 API
    #   { "content_offset_seconds": float, "commenter": {"display_name": ...},
    #     "message": {"body": "..."} }
    if "content_offset_seconds" in item:
        offset = item.get("content_offset_seconds")
        commenter = item.get("commenter") or {}
        author = commenter.get("display_name") or commenter.get("name") or "anonymous"
        msg_obj = item.get("message") or {}
        text = msg_obj.get("body") if isinstance(msg_obj, dict) else str(msg_obj)
        if offset is not None and text:
            return ChatMessage(float(offset), author, str(text).strip())

    # 形式2: GraphQL VideoCommentsByOffsetOrCursor 形式(node構造)
    #   { "node": {"contentOffsetSeconds": ..., "commenter": {"displayName": ...},
    #     "message": {"fragments": [{"text": "..."}]}} }
    node = item.get("node") if "node" in item else item
    if isinstance(node, dict) and "contentOffsetSeconds" in node:
        offset = node.get("contentOffsetSeconds")
        commenter = node.get("commenter") or {}
        author = commenter.get("displayName") or "anonymous"
        fragments = (node.get("message") or {}).get("fragments") or []
        text = "".join((f.get("text") or "") for f in fragments).strip()
        if offset is not None and text:
            return ChatMessage(float(offset), author, text)

    # 形式3: chat-downloader 形式 ({"time_in_seconds": ..., "author": {"name": ...}, "message": ...})
    if "time_in_seconds" in item:
        offset = item.get("time_in_seconds")
        author_obj = item.get("author") or {}
        author = author_obj.get("name") or "anonymous"
        text = item.get("message") or ""
        if offset is not None and text:
            return ChatMessage(float(offset), author, str(text).strip())

    return None


# ========== 共通 ==========

def messages_to_records(messages: Iterable[ChatMessage]) -> list[dict]:
    return [
        {"time_seconds": m.time_seconds, "author": m.author, "text": m.text}
        for m in messages
    ]
