"""コメント本文の形態素解析と頻出単語抽出 / 単語検索。"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache

import pandas as pd
from janome.tokenizer import Tokenizer

# ストップワード(配信コメントの汎用語・1文字平仮名・あいさつ等)
STOPWORDS = {
    "これ", "それ", "あれ", "ここ", "そこ", "あそこ",
    "こと", "もの", "ため", "よう", "とき", "ところ", "ひと", "の",
    "ある", "いる", "する", "なる", "やる", "いう", "見る", "思う", "言う",
    "そう", "どう", "なに", "なん", "もう", "まだ", "まあ",
    "今", "前", "後", "次", "今日", "明日", "昨日",
    "私", "俺", "僕", "あなた", "君", "彼", "彼女",
    "おはよう", "こんにちは", "こんばんは", "おつ", "おつかれ", "草",
    "笑", "www", "wwww", "wwwww", "ww",
    "ー", "～", "ァ", "ィ", "ゥ", "ェ", "ォ",
}

# 1文字の平仮名・カタカナは弾く
_SHORT_KANA_RE = re.compile(r"^[぀-ゟ゠-ヿ]$")


@lru_cache(maxsize=1)
def _tokenizer() -> Tokenizer:
    return Tokenizer()


def extract_keywords(messages: list[dict], top_n: int = 30) -> list[tuple[str, int]]:
    """全コメントから名詞・形容詞を抽出して頻度カウント。上位 top_n を返す。"""
    if not messages:
        return []

    tokenizer = _tokenizer()
    counter: Counter[str] = Counter()

    for m in messages:
        text = m.get("text", "")
        if not text:
            continue
        for token in tokenizer.tokenize(text):
            pos = token.part_of_speech.split(",")[0]
            if pos not in ("名詞", "形容詞"):
                continue
            surface = token.surface.strip()
            if not surface or len(surface) < 2:
                # 2文字未満は基本捨てるが、カタカナ語の単漢字は残す例外なし
                continue
            if surface in STOPWORDS:
                continue
            if _SHORT_KANA_RE.match(surface):
                continue
            # 数字のみは除外
            if surface.isdigit():
                continue
            counter[surface] += 1

    return counter.most_common(top_n)


def search_comments(
    messages: list[dict], keyword: str
) -> pd.DataFrame:
    """指定キーワードを含むコメントを抽出。case-insensitive 部分一致。"""
    if not keyword or not messages:
        return pd.DataFrame(columns=["time_seconds", "author", "text"])

    kw = keyword.lower()
    matched = [
        m for m in messages
        if kw in m.get("text", "").lower()
    ]
    df = pd.DataFrame(matched)
    if df.empty:
        return df
    return df.sort_values("time_seconds").reset_index(drop=True)


def keyword_bin_counts(
    matched: pd.DataFrame, max_seconds: float, bin_seconds: int
) -> pd.DataFrame:
    """検索結果を秒数ビンに分けたカウントを返す(グラフ重ね描き用)。"""
    if matched.empty:
        return pd.DataFrame(columns=["bin_start", "count"])

    matched = matched.copy()
    matched["bin"] = (matched["time_seconds"] // bin_seconds).astype(int)
    counts = matched.groupby("bin").size().reset_index(name="count")
    counts["bin_start"] = counts["bin"] * bin_seconds
    return counts[["bin_start", "count"]]
