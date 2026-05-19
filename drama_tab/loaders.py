"""CSV / videos.json をロードして正規化する。

TikTok Studio の CSV は日付列が "May 18" (年なし) なので、Overview のファイル名
"Overview_YYYY-MM-DD_..." から起点年を読み取り、月が前行より小さくなったタイミングで
年を +1 する形で補完する。

videos.json の数値は "5M" / "8.9%" / "19.46s" / "27722h:24m" / "1.8K" などの
表示用文字列なので、すべて数値(views=整数, time=秒)に正規化する。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


DATA_DIR_DEFAULT = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# 数値パーサ
# ---------------------------------------------------------------------------

def parse_human_number(s: Any) -> float | None:
    """'5M', '1.8K', '12,345', '8.9%', '19.46s', '27722h:24m' を float に。"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None

    # H:M (視聴時間 "27722h:24m" や "1h:23m")
    m = re.match(r"^(\d+)h:?(\d+)?m?$", s)
    if m:
        h = int(m.group(1))
        mm = int(m.group(2) or 0)
        return h * 3600 + mm * 60

    # 単独の "Nm" (分のみ)
    m = re.match(r"^(\d+)m$", s)
    if m:
        return int(m.group(1)) * 60

    # K/M/B
    m = re.match(r"^([\d.]+)\s*([KMB])$", s, re.IGNORECASE)
    if m:
        n = float(m.group(1))
        suf = m.group(2).upper()
        return n * {"K": 1e3, "M": 1e6, "B": 1e9}[suf]

    # %, s, 単純数値 (コンマあり/なし)
    s2 = s.replace(",", "")
    m = re.match(r"^([\d.]+)\s*(?:%|s|秒)?$", s2)
    if m:
        return float(m.group(1))

    return None


def parse_post_date_raw(s: str | None) -> date | None:
    """'2026/3/27に投稿' のような文字列を date に。"""
    if not s:
        return None
    m = re.search(r"(\d{4})[/\-年.](\d{1,2})[/\-月.](\d{1,2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 日付列正規化 ("May 18" → 連番 date)
# ---------------------------------------------------------------------------

_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Sept": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_month_day(s: str) -> tuple[int, int] | None:
    s = (s or "").strip()
    m = re.match(r"^(\w+)\s+(\d{1,2})$", s)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1))
    if not mon:
        return None
    return mon, int(m.group(2))


def normalize_date_column(values: list[str], start_year: int) -> list[date]:
    """連続日付の "May 18", "May 19", ..., "December 31", "January 1", ... を date に。
    月が前行より小さくなったタイミングで年を +1 する。"""
    out: list[date] = []
    year = start_year
    last_month: int | None = None
    for v in values:
        md = _parse_month_day(str(v))
        if md is None:
            out.append(None)  # type: ignore[arg-type]
            continue
        mon, day = md
        if last_month is not None and mon < last_month:
            year += 1
        try:
            d = date(year, mon, day)
        except ValueError:
            d = None  # type: ignore[assignment]
        out.append(d)
        last_month = mon
    return out


def detect_start_year(data_dir: Path) -> int:
    """Overview ファイル名 'Overview_YYYY-MM-DD_*' から起点年を取る。
    見つからなければ今年-1 をデフォルト。"""
    for p in data_dir.glob("**/Overview_*.csv"):
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", p.name)
        if m:
            # 起点年 = export_year - 1 (365d 前)
            export_year = int(m.group(1))
            export_month = int(m.group(2))
            # data starts at export_date - 365 days
            # 簡略化: export_year - 1 を起点年に
            return export_year - 1
    return datetime.now().year - 1


# ---------------------------------------------------------------------------
# CSV ローダ
# ---------------------------------------------------------------------------

# CSV 名 → 期待する列
CSV_SPECS = {
    "Overview": ["Date", "Video Views", "Profile Views", "Likes", "Comments", "Shares"],
    "Viewers": ["Date", "Total Viewers", "New Viewers", "Returning Viewers"],
    "FollowerHistory": ["Date", "Followers", "Difference in followers from previous day"],
    "FollowerActivity": ["Date", "Hour", "Active followers"],
    "FollowerGender": ["Gender", "Distribution"],
    "FollowerTopTerritories": ["Top territories", "Distribution"],
}


def find_csv(data_dir: Path, name: str) -> Path | None:
    """data_dir 配下から `<Name>*.csv` を探す。"""
    for p in data_dir.rglob(f"{name}*.csv"):
        if p.is_file():
            return p
    # 別名(Overviewはダウンロード時に長いファイル名が付く)
    for p in data_dir.rglob("*.csv"):
        if p.stem.startswith(name) or name in p.parent.name:
            return p
    return None


def load_overview(path: Path, start_year: int) -> pd.DataFrame:
    df = pd.read_csv(path)
    dates = normalize_date_column(df["Date"].tolist(), start_year)
    df.insert(0, "date", pd.to_datetime(dates))
    for col in ["Video Views", "Profile Views", "Likes", "Comments", "Shares"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_viewers(path: Path, start_year: int) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.insert(0, "date", pd.to_datetime(normalize_date_column(df["Date"].tolist(), start_year)))
    for col in ["Total Viewers", "New Viewers", "Returning Viewers"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_follower_history(path: Path, start_year: int) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.insert(0, "date", pd.to_datetime(normalize_date_column(df["Date"].tolist(), start_year)))
    df["Followers"] = pd.to_numeric(df["Followers"], errors="coerce")
    df["Difference in followers from previous day"] = pd.to_numeric(
        df["Difference in followers from previous day"], errors="coerce"
    )
    return df


def load_follower_activity(path: Path, start_year: int) -> pd.DataFrame:
    """7日 × 24h の活動量。日付は7日分しか無いが年補完は同じロジックで一応かける。"""
    df = pd.read_csv(path)
    df.insert(0, "date", pd.to_datetime(normalize_date_column(df["Date"].tolist(), start_year)))
    df["Hour"] = pd.to_numeric(df["Hour"], errors="coerce")
    df["Active followers"] = pd.to_numeric(df["Active followers"], errors="coerce")
    return df


def load_follower_gender(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Distribution"] = pd.to_numeric(df["Distribution"], errors="coerce")
    return df


def load_follower_territories(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Distribution"] = pd.to_numeric(df["Distribution"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# videos.json ローダ
# ---------------------------------------------------------------------------

def load_videos_json(path: Path) -> pd.DataFrame:
    """data/videos.json を読んで、スクレイプ済み行だけ DataFrame に。
    analytics=None の行(未スクレイプ)はスキップする。"""
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "id", "title", "post_date", "url",
                "views", "total_watch_time_sec", "avg_watch_time_sec",
                "completion_rate", "new_followers",
            ]
        )

    raw = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for vid, v in raw.items():
        a = v.get("analytics") or {}
        m = a.get("metrics") or {}
        # 未スクレイプ or 完全 0 はスキップ (= 予約/下書き等)
        views = parse_human_number(m.get("views"))
        if views is None:
            continue
        rows.append(
            {
                "id": vid,
                "title": (a.get("title") or "").strip(),
                "post_date": parse_post_date_raw(a.get("post_date_raw")),
                "url": a.get("url"),
                "views": views,
                "total_watch_time_sec": parse_human_number(m.get("total_watch_time")),
                "avg_watch_time_sec": parse_human_number(m.get("avg_watch_time")),
                "completion_rate": parse_human_number(m.get("completion_rate")),
                "new_followers": parse_human_number(m.get("new_followers")),
                "scraped_at": v.get("scraped_at"),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["post_date"] = pd.to_datetime(df["post_date"])
        df["engagement_rate"] = None  # CSV で補完しない(動画別の Likes/Comments は Content CSV にしか無い)
    return df


# ---------------------------------------------------------------------------
# まとめロード
# ---------------------------------------------------------------------------

@dataclass
class StudioData:
    overview: pd.DataFrame | None
    viewers: pd.DataFrame | None
    follower_history: pd.DataFrame | None
    follower_activity: pd.DataFrame | None
    follower_gender: pd.DataFrame | None
    follower_territories: pd.DataFrame | None
    videos: pd.DataFrame
    start_year: int
    n_videos_total: int  # videos.json に含まれる総行数(未スクレイプ含む)
    n_videos_scraped: int  # 数値が入っている行数


def load_all(data_dir: Path = DATA_DIR_DEFAULT) -> StudioData:
    start_year = detect_start_year(data_dir)

    def _try(name: str, loader):
        p = find_csv(data_dir, name)
        if p is None:
            return None
        try:
            return loader(p) if loader.__code__.co_argcount == 1 else loader(p, start_year)
        except Exception as e:
            print(f"warn: {name} ロード失敗: {e}")
            return None

    overview = _try("Overview", load_overview)
    viewers = _try("Viewers", load_viewers)
    fh = _try("FollowerHistory", load_follower_history)
    fa = _try("FollowerActivity", load_follower_activity)
    fg = _try("FollowerGender", load_follower_gender)
    ft = _try("FollowerTopTerritories", load_follower_territories)

    videos_json = data_dir / "videos.json"
    videos = load_videos_json(videos_json)

    n_total = 0
    if videos_json.exists():
        try:
            raw = json.loads(videos_json.read_text(encoding="utf-8"))
            n_total = len(raw)
        except Exception:
            n_total = 0

    return StudioData(
        overview=overview,
        viewers=viewers,
        follower_history=fh,
        follower_activity=fa,
        follower_gender=fg,
        follower_territories=ft,
        videos=videos,
        start_year=start_year,
        n_videos_total=n_total,
        n_videos_scraped=len(videos),
    )
