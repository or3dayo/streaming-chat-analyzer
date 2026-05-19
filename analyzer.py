"""コメント時系列のビン分け + ピーク検出。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Peak:
    bin_start: float  # 秒
    bin_end: float
    count: int
    messages: pd.DataFrame  # その帯のコメント


def build_timeline(messages: list[dict], bin_seconds: int) -> pd.DataFrame:
    """秒単位ビンごとのコメント数を返す DataFrame を作る。

    列: bin_start (秒), bin_end (秒), count, label (mm:ss)
    """
    if not messages:
        return pd.DataFrame(columns=["bin_start", "bin_end", "count", "label"])

    df = pd.DataFrame(messages)
    df["bin"] = (df["time_seconds"] // bin_seconds).astype(int)

    counts = df.groupby("bin").size().reset_index(name="count")
    max_bin = int(df["bin"].max())
    all_bins = pd.DataFrame({"bin": range(max_bin + 1)})
    timeline = all_bins.merge(counts, on="bin", how="left").fillna({"count": 0})
    timeline["count"] = timeline["count"].astype(int)
    timeline["bin_start"] = timeline["bin"] * bin_seconds
    timeline["bin_end"] = timeline["bin_start"] + bin_seconds
    timeline["label"] = timeline["bin_start"].apply(format_timestamp)
    return timeline[["bin_start", "bin_end", "count", "label"]]


def find_peaks(
    messages: list[dict],
    timeline: pd.DataFrame,
    top_n: int = 20,
    min_gap_bins: int = 2,
) -> list[Peak]:
    """カウント上位 N 件のピークを抽出。近接ビンはマージして1件にまとめる。"""
    if timeline.empty:
        return []

    df = pd.DataFrame(messages)
    sorted_bins = timeline.sort_values("count", ascending=False).reset_index(drop=True)

    picked: list[tuple[float, float, int]] = []  # (start, end, count)
    for _, row in sorted_bins.iterrows():
        if row["count"] == 0:
            break
        start = row["bin_start"]
        end = row["bin_end"]
        bin_size = end - start

        # 既存ピークと近接していたらマージ
        merged = False
        for i, (s, e, c) in enumerate(picked):
            if start >= s - bin_size * min_gap_bins and end <= e + bin_size * min_gap_bins:
                new_s = min(s, start)
                new_e = max(e, end)
                picked[i] = (new_s, new_e, c + row["count"])
                merged = True
                break
        if not merged:
            picked.append((start, end, int(row["count"])))
        if len(picked) >= top_n:
            break

    peaks: list[Peak] = []
    for s, e, c in picked:
        chunk = df[(df["time_seconds"] >= s) & (df["time_seconds"] < e)].sort_values(
            "time_seconds"
        )
        peaks.append(Peak(bin_start=s, bin_end=e, count=c, messages=chunk))

    peaks.sort(key=lambda p: p.bin_start)
    return peaks


DEFAULT_FPS = 60


def format_timestamp(seconds: float, fps: int = DEFAULT_FPS) -> str:
    """Premiere Pro 形式のタイムコード `HH:MM:SS:FF` を返す(60fps基準)。"""
    if seconds is None or seconds < 0:
        return "00:00:00:00"
    total_seconds = int(seconds)
    frames = int(round((seconds - total_seconds) * fps))
    if frames >= fps:
        total_seconds += frames // fps
        frames = frames % fps
    h, rem = divmod(total_seconds, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}:{frames:02d}"


def make_youtube_timestamp_url(base_url: str, seconds: float) -> str:
    """YouTube URLに ?t=Xs を付けて該当秒数にジャンプするリンクを作る。"""
    s = int(seconds)
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}t={s}s"
