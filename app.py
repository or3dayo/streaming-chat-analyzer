"""配信アーカイブのコメントアクティブ率を可視化し、切り抜き候補を要約するWeb UI。"""

from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from analyzer import (
    Peak,
    build_timeline,
    find_peaks,
    format_timestamp,
    make_youtube_timestamp_url,
)
from chat_fetcher import fetch_chat, fetch_chat_from_json_text, messages_to_records
from summarizer import PeakSummary, summarize_peaks

load_dotenv()

st.set_page_config(page_title="配信コメント分析", layout="wide")


def _get_secret(key: str, default: str = "") -> str:
    """Streamlit Cloud の Secrets → 環境変数 → デフォルト の優先順で取得。"""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)


def _password_gate() -> bool:
    """APP_PASSWORD が設定されていればパスワード入力を要求。未設定なら素通り。"""
    expected = _get_secret("APP_PASSWORD")
    if not expected:
        return True
    if st.session_state.get("auth_ok"):
        return True

    st.title("ログイン")
    pw = st.text_input("パスワード", type="password")
    if pw:
        if pw == expected:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    return False


if not _password_gate():
    st.stop()

st.title("配信コメントアクティブ率 可視化 & 切り抜き候補抽出")
st.caption("YouTube Live / Twitch のアーカイブから、コメントの盛り上がりと要約を出します。")

# APIキーは Secrets / .env から自動読み込み
api_key = _get_secret("ANTHROPIC_API_KEY")

# ---- サイドバー ----
with st.sidebar:
    st.header("設定")
    bin_seconds = st.slider("ビン幅(秒)", 10, 120, 30, step=10)
    top_n = st.slider("要約するピーク数(上位N)", 5, 30, 20)
    max_comments = st.slider("ピーク1件あたりの最大コメント数", 10, 80, 40, step=10)
    if not api_key:
        st.warning("⚠ APIキー未設定です(管理者へ連絡)")

# ---- メイン ----
mode = st.radio(
    "入力方法",
    ["URL から取得", "ローカル JSON をアップロード(Twitch推奨)"],
    horizontal=True,
)

url = ""
uploaded_file = None

if mode == "URL から取得":
    url = st.text_input(
        "配信URL(YouTube は OK、Twitchは現状API側でブロック)",
        placeholder="https://www.youtube.com/watch?v=...",
    )
    run = st.button("解析する", type="primary", disabled=not url)
else:
    with st.expander("📥 chat.json の作り方(TwitchDownloaderCLI)", expanded=False):
        st.markdown(
            """
1. [TwitchDownloader Releases](https://github.com/lay295/TwitchDownloader/releases) から
   `TwitchDownloaderCLI-*-Windows-x64.zip` をDL、展開
2. PowerShellで:
   ```powershell
   .\\TwitchDownloaderCLI.exe chatdownload --id 2771590829 -o chat.json
   ```
   (`--id` には Twitch VOD URL末尾の数字)
3. できた `chat.json` を下のフォームにアップロード
"""
        )
    uploaded_file = st.file_uploader(
        "chat.json をドラッグ&ドロップ", type=["json"], accept_multiple_files=False
    )
    run = st.button("解析する", type="primary", disabled=uploaded_file is None)

if run:
    if not api_key:
        st.error("Anthropic APIキーを設定してください(サイドバー)。")
        st.stop()

    fetch_status = st.empty()
    fetch_status.info("チャットを読み込み中…(長尺だと時間かかります)")
    try:
        progress = st.progress(0, text="開始")

        def on_progress(n: int):
            progress.progress(min(n / 50000, 1.0), text=f"{n} 件読み込み")

        if mode == "URL から取得":
            messages = fetch_chat(url, progress_cb=on_progress)
            source_label = url
        else:
            raw = uploaded_file.read().decode("utf-8", errors="replace")
            messages = fetch_chat_from_json_text(raw, progress_cb=on_progress)
            source_label = uploaded_file.name
        progress.empty()
    except Exception as e:
        fetch_status.error(f"取得失敗: {e}")
        st.stop()

    if not messages:
        fetch_status.warning("コメントが見つかりませんでした。")
        st.stop()
    fetch_status.success(f"{len(messages)} 件のコメントを読み込みました。")

    records = messages_to_records(messages)
    st.session_state["records"] = records
    st.session_state["url"] = source_label

# 取得済みデータがあれば表示・要約
if "records" in st.session_state:
    records = st.session_state["records"]
    url_for_links = st.session_state.get("url", "")

    timeline = build_timeline(records, bin_seconds)
    peaks = find_peaks(records, timeline, top_n=top_n)

    # --- 2. グラフ ---
    st.subheader("コメントアクティブ率")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=timeline["bin_start"],
            y=timeline["count"],
            mode="lines",
            name="コメント数",
            line=dict(color="#4C9AFF", width=1.5),
            fill="tozeroy",
            fillcolor="rgba(76,154,255,0.2)",
            hovertemplate="時刻 %{customdata}<br>コメント数 %{y}<extra></extra>",
            customdata=timeline["label"],
        )
    )
    if peaks:
        fig.add_trace(
            go.Scatter(
                x=[p.bin_start for p in peaks],
                y=[p.count for p in peaks],
                mode="markers",
                name="ピーク",
                marker=dict(color="#FF5630", size=10, symbol="diamond"),
                hovertemplate="ピーク %{customdata}<br>コメント数 %{y}<extra></extra>",
                customdata=[format_timestamp(p.bin_start) for p in peaks],
            )
        )
    fig.update_layout(
        height=380,
        xaxis_title="配信秒数",
        yaxis_title=f"コメント数 / {bin_seconds}秒",
        margin=dict(l=40, r=20, t=20, b=40),
        hovermode="x",
    )
    st.plotly_chart(fig, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("総コメント数", f"{len(records):,}")
    col2.metric("配信長", format_timestamp(timeline["bin_end"].max()))
    col3.metric("ピーク検出数", len(peaks))

    # --- 3. 要約 ---
    st.subheader(f"切り抜き候補 (ピーク上位 {len(peaks)} 件)")

    summarize_btn_key = f"summarize_{bin_seconds}_{top_n}_{max_comments}"
    if st.button("ピーク帯をClaudeで要約する", key="summarize_btn"):
        prog = st.progress(0, text="要約中…")

        def on_sum_progress(done: int, total: int):
            prog.progress(done / total, text=f"要約中 {done}/{total}")

        with st.spinner("Claude API 呼び出し中…"):
            summaries = summarize_peaks(
                peaks,
                api_key=api_key,
                max_comments_per_peak=max_comments,
                progress_cb=on_sum_progress,
            )
        prog.empty()
        st.session_state[summarize_btn_key] = summaries

    summaries: list[PeakSummary] | None = st.session_state.get(summarize_btn_key)

    # ピーク一覧表示
    for i, peak in enumerate(peaks):
        ts_label = format_timestamp(peak.bin_start)
        with st.expander(
            f"#{i+1}  {ts_label}  ({peak.count} コメント / {int(peak.bin_end - peak.bin_start)}秒)",
            expanded=(i < 3),
        ):
            left, right = st.columns([2, 3])
            with left:
                if "youtube.com" in url_for_links or "youtu.be" in url_for_links:
                    jump_url = make_youtube_timestamp_url(url_for_links, peak.bin_start)
                    st.markdown(f"[▶ {ts_label} にジャンプ]({jump_url})")
                else:
                    st.markdown(f"**配信時刻:** {ts_label}")
                st.markdown(f"**コメント数:** {peak.count}")
                if summaries and i < len(summaries):
                    st.markdown("**要約**")
                    st.write(summaries[i].summary)
            with right:
                st.markdown("**代表コメント(抜粋)**")
                sample = peak.messages.head(15)
                for _, row in sample.iterrows():
                    st.text(f"[{format_timestamp(row['time_seconds'])}] {row['author']}: {row['text']}")

    # --- 4. エクスポート ---
    st.subheader("エクスポート")
    if summaries:
        export_df = pd.DataFrame(
            {
                "timestamp": [format_timestamp(s.bin_start) for s in summaries],
                "seconds": [int(s.bin_start) for s in summaries],
                "comment_count": [s.count for s in summaries],
                "summary": [s.summary for s in summaries],
                "jump_url": [
                    make_youtube_timestamp_url(url_for_links, s.bin_start)
                    if ("youtube.com" in url_for_links or "youtu.be" in url_for_links)
                    else ""
                    for s in summaries
                ],
            }
        )
        st.download_button(
            "切り抜き候補をCSVでダウンロード",
            data=export_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="clip_candidates.csv",
            mime="text/csv",
        )
    else:
        st.caption("要約を実行するとCSVエクスポートできます。")
