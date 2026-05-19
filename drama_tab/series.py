"""動画タイトルからシリーズ名とエピソード番号を抽出する。

タイトルの例:
  - "アンガージュマン_10話"            → ("アンガージュマン", 10)
  - "Ep.4"                              → (None, 4)
  - "== 「世間体」 == ［出演］...41_31_2_1" → ("世間体", None, internal_id="41_31_2_1")
  - "続き...== いい子、わるい子 == ...ID: 70_15_4_2" → ("いい子、わるい子", None)
  - "== 監視対象はあなたです―悪夢の不倫温泉== ..."  → ("監視対象はあなたです―悪夢の不倫温泉", None)

エピソード番号が取れない場合、内部ID末尾の "X_Y_Z" から推測する余地もあるが、
ここでは確実なパターンのみ抽出する。後でユーザーが手動マッピングできる UI を用意するのが現実解。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class SeriesInfo:
    series: str | None
    episode: int | None
    internal_id: str | None  # 例: "41_31_2_1" や "70_15_4_2"


_SERIES_PATTERNS = [
    # == 「シリーズ名」 ==
    re.compile(r"==\s*[「『](?P<s>[^」』]{2,40})[」』]\s*=="),
    # == シリーズ名 == (記号で囲まれない)
    re.compile(r"==\s*(?P<s>[^=「『」』]{2,40}?)\s*=="),
    # ==シリーズ名== (スペース無し)
    re.compile(r"==(?P<s>[^=「『」』]{2,40}?)=="),
]

_EP_PATTERNS = [
    re.compile(r"_(?P<n>\d{1,3})話"),
    re.compile(r"Ep\.?\s*(?P<n>\d{1,3})", re.IGNORECASE),
    re.compile(r"第(?P<n>\d{1,3})話"),
]

# "ID: 70_15_4_2" や末尾の "_70_15_4_2"
_INTERNAL_ID_PATTERN = re.compile(r"(?:ID[:：]\s*|\s)(\d{1,3}_\d{1,3}_\d{1,3}_\d{1,3})")


def extract_series_info(title: str) -> SeriesInfo:
    if not title:
        return SeriesInfo(None, None, None)

    series: str | None = None
    for pat in _SERIES_PATTERNS:
        m = pat.search(title)
        if m:
            s = m.group("s").strip()
            # 「監督」「脚本」「出演」 などのスタッフ表記が混入したら除外
            if any(kw in s for kw in ["監督", "脚本", "出演", "制作", "スタッフ", "[", "］", "■"]):
                continue
            if 2 <= len(s) <= 40:
                series = s
                break

    episode: int | None = None
    for pat in _EP_PATTERNS:
        m = pat.search(title)
        if m:
            episode = int(m.group("n"))
            break

    internal: str | None = None
    m = _INTERNAL_ID_PATTERN.search(title)
    if m:
        internal = m.group(1)

    return SeriesInfo(series=series, episode=episode, internal_id=internal)


def attach_series_columns(df):
    """DataFrame に series / episode / internal_id 列を追加。"""
    import pandas as pd

    if df is None or df.empty:
        return df
    info = df["title"].fillna("").map(extract_series_info)
    df["series"] = [i.series for i in info]
    df["episode"] = [i.episode for i in info]
    df["internal_id"] = [i.internal_id for i in info]
    # internal_id があれば末尾の "_X_Y" を補助的にエピソード推定に使う
    # 例: "70_15_4_2" → (70=series_code, 15=?, 4=ep, 2=cut) ※仮説
    # 確証無いので episode 列が空の時のみ第3要素を仮置き
    def _ep_from_internal(row):
        if row["episode"] is not None and not pd.isna(row["episode"]):
            return row["episode"]
        iid = row["internal_id"]
        if not iid:
            return None
        parts = iid.split("_")
        if len(parts) >= 3:
            try:
                return int(parts[2])
            except ValueError:
                return None
        return None

    df["episode_guess"] = df.apply(_ep_from_internal, axis=1)
    return df
