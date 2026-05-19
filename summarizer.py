"""Claude API でピーク帯のコメントを要約。"""

from __future__ import annotations

from dataclasses import dataclass

import anthropic
import pandas as pd

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """あなたは配信切り抜き編集者のアシスタントです。
ライブ配信のコメント群から、その瞬間に視聴者が何に反応していたかを要約してください。

出力フォーマット:
- 「何が起きたか」を1〜2文で簡潔に
- 代表的な感情・反応(笑い/驚き/感動/盛り上がり等)を1語
- 切り抜き候補としての魅力度(高/中/低)とその理由を一言

切り抜き選定の観点を意識:盛り上がり、面白い発言、印象的なリアクション、ハイライト性。
不明瞭な場合は推測せず「コメントから判断困難」と書く。"""


@dataclass
class PeakSummary:
    bin_start: float
    bin_end: float
    count: int
    summary: str
    representative_comments: list[str]


def summarize_peaks(
    peaks: list,  # list[Peak]
    api_key: str,
    max_comments_per_peak: int = 40,
    progress_cb=None,
) -> list[PeakSummary]:
    """各ピーク帯のコメントを要約。プロンプトキャッシュでシステムを共有。"""
    client = anthropic.Anthropic(api_key=api_key)
    results: list[PeakSummary] = []

    for i, peak in enumerate(peaks):
        comments = _sample_comments(peak.messages, max_comments_per_peak)
        comments_text = "\n".join(f"- {c}" for c in comments)
        user_message = (
            f"配信時刻 {_fmt(peak.bin_start)} 〜 {_fmt(peak.bin_end)} "
            f"({peak.count}件のコメント) の抜粋:\n\n{comments_text}\n\n"
            f"上記コメントから、その瞬間に何が起きていたか要約してください。"
        )

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=600,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_message}],
            )
            summary_text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
        except anthropic.APIError as e:
            summary_text = f"(要約失敗: {e})"

        results.append(
            PeakSummary(
                bin_start=peak.bin_start,
                bin_end=peak.bin_end,
                count=peak.count,
                summary=summary_text,
                representative_comments=comments[:5],
            )
        )
        if progress_cb:
            progress_cb(i + 1, len(peaks))

    return results


def _sample_comments(df: pd.DataFrame, limit: int) -> list[str]:
    """コメントを取得。多すぎる場合は均等サンプリング。"""
    texts = df["text"].astype(str).tolist()
    if len(texts) <= limit:
        return texts
    step = len(texts) / limit
    return [texts[int(i * step)] for i in range(limit)]


def _fmt(seconds: float) -> str:
    """Premiere Pro形式タイムコード(60fps)。"""
    from analyzer import format_timestamp
    return format_timestamp(seconds)
