"""配信アーカイブのコメントアクティブ率を可視化し、切り抜き候補を要約するWeb UI。

VoltAgent inspired dark theme — void-black canvas + emerald accent.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta

import extra_streamlit_components as stx
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
from word_analyzer import extract_keywords, keyword_bin_counts, search_comments

load_dotenv()

st.set_page_config(
    page_title="Stream Chat Analyzer",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ====== VoltAgent inspired CSS ======
_CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"]  {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

.stApp {
    background-color: #101010;
}

h1, h2, h3 {
    color: #ffffff !important;
    letter-spacing: -0.02em;
    font-weight: 600 !important;
}
h1 { font-size: 36px !important; line-height: 40px !important; }
h2 { font-size: 24px !important; line-height: 32px !important; font-weight: 700 !important; }
h3 { font-size: 20px !important; line-height: 28px !important; }

.eyebrow {
    color: #00d992;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 2.52px;
    text-transform: uppercase;
    margin-bottom: 4px;
}

p, label, .stMarkdown, span {
    color: #bdbdbd !important;
}

/* Primary button (Streamlitの primary) */
.stButton > button[kind="primary"] {
    background-color: #00d992 !important;
    color: #101010 !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    padding: 12px 16px !important;
    transition: all 0.15s ease;
}
.stButton > button[kind="primary"]:hover {
    background-color: #2fd6a1 !important;
    box-shadow: 0 0 15px rgba(0, 217, 146, 0.3);
}

/* Secondary button */
.stButton > button:not([kind="primary"]) {
    background-color: #101010 !important;
    color: #f2f2f2 !important;
    border: 1px solid #3d3a39 !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
}
.stButton > button:not([kind="primary"]):hover {
    border-color: #00d992 !important;
    color: #00d992 !important;
}

/* Input fields */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
    background-color: #1a1a1a !important;
    color: #f2f2f2 !important;
    border: 1px solid #3d3a39 !important;
    border-radius: 6px !important;
}
.stTextInput > div > div > input:focus {
    border-color: #00d992 !important;
}

/* Metric */
[data-testid="stMetric"] {
    background-color: #101010;
    border: 1px solid #3d3a39;
    border-radius: 8px;
    padding: 16px;
}
[data-testid="stMetricLabel"] {
    color: #8b949e !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    letter-spacing: 2px;
    text-transform: uppercase;
}
[data-testid="stMetricValue"] {
    color: #ffffff !important;
    font-weight: 700 !important;
}

/* Expander */
.streamlit-expanderHeader {
    background-color: #101010 !important;
    border: 1px solid #3d3a39 !important;
    border-radius: 8px !important;
    color: #f2f2f2 !important;
    font-weight: 600 !important;
}
.streamlit-expanderHeader:hover {
    border-color: #00d992 !important;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #0a0a0a;
    border-right: 1px solid #3d3a39;
}
section[data-testid="stSidebar"] h2 {
    color: #00d992 !important;
    font-size: 14px !important;
    letter-spacing: 2.52px;
    text-transform: uppercase;
}

/* Code / mono */
code, pre {
    font-family: 'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace !important;
    background-color: #1a1a1a !important;
    color: #f5f6f7 !important;
    border-radius: 4px !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 1px solid #3d3a39;
}
.stTabs [data-baseweb="tab"] {
    background-color: transparent !important;
    color: #bdbdbd !important;
    border-radius: 6px 6px 0 0 !important;
    padding: 12px 16px !important;
    font-weight: 600 !important;
}
.stTabs [aria-selected="true"] {
    color: #00d992 !important;
    border-bottom: 2px solid #00d992 !important;
}

/* File uploader */
[data-testid="stFileUploader"] section {
    background-color: #1a1a1a !important;
    border: 1px dashed #3d3a39 !important;
    border-radius: 8px !important;
}

/* Divider */
hr {
    border-color: #3d3a39 !important;
}

/* Alerts (緑系/青系の通知でテキストが薄くなるのを防ぐ) */
div[data-testid="stAlert"] {
    border-radius: 8px !important;
    border: 1px solid #3d3a39 !important;
}
/* st.success の緑系背景上は黒文字 */
div[data-testid="stAlert"][data-baseweb="notification"][kind="success"],
div[data-baseweb="notification"][kind="success"] {
    background-color: #00d992 !important;
}
div[data-testid="stAlert"][data-baseweb="notification"][kind="success"] *,
div[data-baseweb="notification"][kind="success"] * {
    color: #101010 !important;
}

/* 頻出単語ハイライト用ボタン(primary 状態) */
.stButton > button[kind="primary"] {
    color: #101010 !important;
}
.stButton > button[kind="primary"] * {
    color: #101010 !important;
}

/* Progress bar */
.stProgress > div > div > div {
    background-color: #00d992 !important;
}

/* Status pill */
.status-pill {
    display: inline-block;
    padding: 4px 12px;
    border: 1px solid #3d3a39;
    border-radius: 9999px;
    font-size: 12px;
    font-weight: 600;
    color: #00d992;
    background: #101010;
}
</style>
"""
st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)


# ====== Auth & secrets ======
def _get_secret(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)


COOKIE_NAME = "chat_analyzer_auth_v1"


@st.cache_resource
def _cookie_manager() -> stx.CookieManager:
    return stx.CookieManager()


def _hash_password(pw: str) -> str:
    return hashlib.sha256(f"chat-analyzer::{pw}".encode("utf-8")).hexdigest()


def _password_gate() -> bool:
    expected = _get_secret("APP_PASSWORD")
    if not expected:
        return True

    # セッション内で認証済みなら素通し
    if st.session_state.get("auth_ok"):
        return True

    # クッキーで認証済みかチェック
    cookies = _cookie_manager()
    expected_token = _hash_password(expected)
    saved_token = cookies.get(COOKIE_NAME)
    if saved_token == expected_token:
        st.session_state["auth_ok"] = True
        return True

    # ログイン画面表示
    st.markdown('<div class="eyebrow">ACCESS</div>', unsafe_allow_html=True)
    st.title("Stream Chat Analyzer")
    pw = st.text_input("パスワード", type="password")
    remember = st.checkbox("このブラウザにログインを保存(30日間)", value=True)
    if pw:
        if pw == expected:
            st.session_state["auth_ok"] = True
            if remember:
                cookies.set(
                    COOKIE_NAME,
                    expected_token,
                    expires_at=datetime.now() + timedelta(days=30),
                )
            st.rerun()
        else:
            st.error("パスワードが違います")
    return False


def _logout():
    """ログアウト処理:セッション状態クリア + クッキー削除。"""
    st.session_state["auth_ok"] = False
    try:
        _cookie_manager().delete(COOKIE_NAME)
    except Exception:
        pass
    st.rerun()


if not _password_gate():
    st.stop()


# ====== Header ======
st.markdown('<div class="eyebrow">STREAM CHAT ANALYZER</div>', unsafe_allow_html=True)
st.title("配信コメントアクティブ率 可視化 & 切り抜き候補抽出")
st.caption("YouTube Live / Twitch のアーカイブから、コメントの盛り上がりと要約を出します。")

api_key = _get_secret("ANTHROPIC_API_KEY")

# ====== Sidebar ======
with st.sidebar:
    st.header("SETTINGS")
    bin_seconds = st.slider("ビン幅(秒)", 10, 120, 30, step=10)
    top_n = st.slider("要約するピーク数", 5, 30, 20)
    max_comments = st.slider("ピーク1件あたりの最大コメント数", 10, 80, 40, step=10)
    st.markdown("---")
    st.caption("Timecode: **60fps** (Premiere Pro)")
    if not api_key:
        st.warning("⚠ APIキー未設定です(管理者へ連絡)")
    else:
        st.markdown('<span class="status-pill">API READY</span>', unsafe_allow_html=True)

    st.markdown("---")
    if _get_secret("APP_PASSWORD") and st.button("ログアウト", key="logout_btn"):
        _logout()


# ====== Input ======
st.markdown("---")
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
    with st.expander("chat.json の作り方 (TwitchDownloaderCLI)", expanded=False):
        st.markdown(
            """
1. [TwitchDownloader Releases](https://github.com/lay295/TwitchDownloader/releases) から
   `TwitchDownloaderCLI-*-Windows-x64.zip` をDL、展開
2. PowerShellで:
   ```
   .\\TwitchDownloaderCLI.exe chatdownload --id 2771590829 -o chat.json
   ```
3. できた `chat.json` を下のフォームにアップロード
"""
        )
    uploaded_file = st.file_uploader(
        "chat.json をドラッグ&ドロップ", type=["json"], accept_multiple_files=False
    )
    run = st.button("解析する", type="primary", disabled=uploaded_file is None)


# ====== 取得実行 ======
if run:
    fetch_status = st.empty()
    fetch_status.info("チャットを読み込み中…")
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

    st.session_state["records"] = messages_to_records(messages)
    st.session_state["url"] = source_label


# ====== 解析結果表示 ======
if "records" in st.session_state:
    records = st.session_state["records"]
    url_for_links = st.session_state.get("url", "")

    timeline = build_timeline(records, bin_seconds)
    peaks = find_peaks(records, timeline, top_n=top_n)

    st.markdown("---")
    st.markdown('<div class="eyebrow">OVERVIEW</div>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("総コメント数", f"{len(records):,}")
    col2.metric("配信長", format_timestamp(timeline["bin_end"].max()))
    col3.metric("ピーク検出数", len(peaks))

    # ====== タブ ======
    tab_graph, tab_keywords, tab_search, tab_peaks = st.tabs(
        ["📈 アクティブ率", "🔠 頻出単語", "🔍 単語検索", "🎬 切り抜き候補"]
    )

    # --- グラフタブ ---
    with tab_graph:
        highlight_kw = st.session_state.get("highlight_keyword")

        # ホバー用:各ビンの代表コメント(最大5件)を事前計算
        df_for_hover = pd.DataFrame(records)
        df_for_hover["bin"] = (df_for_hover["time_seconds"] // bin_seconds).astype(int)
        bin_to_comments: dict[int, list[str]] = {}
        for bin_idx, group in df_for_hover.groupby("bin"):
            bin_to_comments[int(bin_idx)] = group.head(6)["text"].astype(str).tolist()

        def _hover_preview(bin_start: float, limit: int = 5, max_len: int = 32) -> str:
            bin_idx = int(bin_start // bin_seconds)
            comments = bin_to_comments.get(bin_idx, [])
            if not comments:
                return "<i>(コメント無し)</i>"
            lines = []
            for c in comments[:limit]:
                # HTMLエスケープ簡易対応
                safe = c.replace("<", "&lt;").replace(">", "&gt;")
                truncated = safe[:max_len] + ("…" if len(safe) > max_len else "")
                lines.append(f"・{truncated}")
            if len(comments) > limit:
                lines.append(f"<i>… 他 {len(comments) - limit} 件</i>")
            return "<br>".join(lines)

        hover_data = [
            [format_timestamp(row["bin_start"]), _hover_preview(row["bin_start"])]
            for _, row in timeline.iterrows()
        ]

        fig = go.Figure()
        # 全体波形(ハイライト有りなら薄め)
        base_color = "#3d3a39" if highlight_kw else "#00d992"
        base_fill = "rgba(61,58,57,0.25)" if highlight_kw else "rgba(0,217,146,0.15)"
        fig.add_trace(
            go.Scatter(
                x=timeline["bin_start"],
                y=timeline["count"],
                mode="lines",
                name="全コメント数",
                line=dict(color=base_color, width=1.5),
                fill="tozeroy",
                fillcolor=base_fill,
                customdata=hover_data,
                hovertemplate=(
                    "<b>%{customdata[0]}</b>  "
                    "<span style='color:#00d992'>%{y} コメント</span><br>"
                    "<span style='color:#8b949e;font-size:11px'>"
                    "──────────────</span><br>"
                    "%{customdata[1]}"
                    "<extra></extra>"
                ),
            )
        )

        # キーワードハイライト重ね描き
        if highlight_kw:
            matched = search_comments(records, highlight_kw)
            hit_counts = keyword_bin_counts(
                matched, timeline["bin_end"].max(), bin_seconds
            )
            if not hit_counts.empty:
                fig.add_trace(
                    go.Bar(
                        x=hit_counts["bin_start"],
                        y=hit_counts["count"],
                        name=f'"{highlight_kw}" 出現',
                        marker=dict(color="#00d992"),
                        hovertemplate="%{customdata}<br>%{y} 件<extra></extra>",
                        customdata=[format_timestamp(s) for s in hit_counts["bin_start"]],
                    )
                )

        if peaks:
            peak_hover = []
            for p in peaks:
                samples = p.messages.head(6)["text"].astype(str).tolist()
                lines = []
                for c in samples[:5]:
                    safe = c.replace("<", "&lt;").replace(">", "&gt;")
                    truncated = safe[:32] + ("…" if len(safe) > 32 else "")
                    lines.append(f"・{truncated}")
                if len(samples) > 5:
                    lines.append(f"<i>… 他 {len(samples) - 5}件</i>")
                preview = "<br>".join(lines) if lines else "<i>(無し)</i>"
                peak_hover.append([format_timestamp(p.bin_start), preview])

            fig.add_trace(
                go.Scatter(
                    x=[p.bin_start for p in peaks],
                    y=[p.count for p in peaks],
                    mode="markers",
                    name="ピーク",
                    marker=dict(color="#ffffff", size=10, symbol="diamond",
                                line=dict(color="#00d992", width=2)),
                    customdata=peak_hover,
                    hovertemplate=(
                        "<b>🎬 ピーク %{customdata[0]}</b>  "
                        "<span style='color:#00d992'>%{y} コメント</span><br>"
                        "<span style='color:#8b949e;font-size:11px'>"
                        "──────────────</span><br>"
                        "%{customdata[1]}"
                        "<extra></extra>"
                    ),
                )
            )
        fig.update_layout(
            height=520,
            xaxis_title="配信秒数",
            yaxis_title=f"コメント数 / {bin_seconds}秒",
            margin=dict(l=40, r=20, t=20, b=40),
            hovermode="x",
            dragmode="pan",
            paper_bgcolor="#101010",
            plot_bgcolor="#101010",
            font=dict(color="#f2f2f2", family="Inter"),
            xaxis=dict(
                gridcolor="#3d3a39",
                zerolinecolor="#3d3a39",
                rangeslider=dict(
                    visible=True,
                    bgcolor="#1a1a1a",
                    bordercolor="#3d3a39",
                    borderwidth=1,
                    thickness=0.08,
                ),
                fixedrange=False,
            ),
            yaxis=dict(
                gridcolor="#3d3a39",
                zerolinecolor="#3d3a39",
                fixedrange=True,  # 縦方向は固定(Pr的に横移動だけ自由)
            ),
            legend=dict(bgcolor="#1a1a1a", bordercolor="#3d3a39", borderwidth=1),
            barmode="overlay",
            hoverlabel=dict(
                bgcolor="#1a1a1a",
                bordercolor="#00d992",
                font=dict(color="#f2f2f2", family="Inter", size=12),
                align="left",
            ),
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={
                "scrollZoom": True,
                "displaylogo": False,
                "modeBarButtonsToRemove": [
                    "select2d", "lasso2d", "autoScale2d",
                ],
                "displayModeBar": "hover",
            },
        )
        st.caption(
            "💡 **操作:** ドラッグ=パン / スクロール=ズーム / ダブルクリック=全体表示 / 下バー=範囲指定 / カーソル乗せ=コメント内容表示"
        )

        if highlight_kw:
            st.caption(
                f'🟢 ハイライト中: "{highlight_kw}" — 解除は「頻出単語」タブから'
            )

    # --- 頻出単語タブ ---
    with tab_keywords:
        with st.spinner("形態素解析中…"):
            keywords = extract_keywords(records, top_n=30)
        if not keywords:
            st.info("単語が抽出できませんでした。")
        else:
            words, counts = zip(*keywords)
            kw_fig = go.Figure(
                go.Bar(
                    x=list(counts),
                    y=list(words),
                    orientation="h",
                    marker=dict(color="#00d992"),
                    hovertemplate="%{y}: %{x}回<extra></extra>",
                )
            )
            kw_fig.update_layout(
                height=max(400, len(words) * 22),
                margin=dict(l=20, r=20, t=20, b=40),
                paper_bgcolor="#101010",
                plot_bgcolor="#101010",
                font=dict(color="#f2f2f2", family="Inter"),
                xaxis=dict(gridcolor="#3d3a39", title="出現回数"),
                yaxis=dict(autorange="reversed", gridcolor="#3d3a39"),
            )
            st.plotly_chart(kw_fig, use_container_width=True)

            st.markdown("**単語をクリックするとアクティブ率グラフ上にハイライト**")
            current_hl = st.session_state.get("highlight_keyword")
            cols = st.columns(6)
            for i, (w, c) in enumerate(keywords[:18]):
                is_selected = (w == current_hl)
                label = f"{w} ({c})"
                btn_type = "primary" if is_selected else "secondary"
                if cols[i % 6].button(label, key=f"kw_chip_{w}", type=btn_type, use_container_width=True):
                    st.session_state["highlight_keyword"] = None if is_selected else w
                    st.rerun()

            if current_hl:
                st.markdown(
                    f'選択中: <span class="status-pill">{current_hl}</span> '
                    "(「アクティブ率」タブで分布を確認)",
                    unsafe_allow_html=True,
                )
                if st.button("ハイライト解除", key="clear_hl"):
                    st.session_state["highlight_keyword"] = None
                    st.rerun()

    # --- 単語検索タブ ---
    with tab_search:
        keyword = st.text_input(
            "検索キーワード",
            placeholder="例: 草, すごい, かわいい",
            key="search_keyword",
        )
        if keyword:
            matched = search_comments(records, keyword)
            st.markdown(
                f'<span class="status-pill">{len(matched)} 件ヒット</span>',
                unsafe_allow_html=True,
            )

            if not matched.empty:
                # グラフに重ね描き
                hit_counts = keyword_bin_counts(
                    matched, timeline["bin_end"].max(), bin_seconds
                )
                search_fig = go.Figure()
                search_fig.add_trace(
                    go.Scatter(
                        x=timeline["bin_start"],
                        y=timeline["count"],
                        mode="lines",
                        name="全体",
                        line=dict(color="#3d3a39", width=1),
                        fill="tozeroy",
                        fillcolor="rgba(61,58,57,0.3)",
                        hoverinfo="skip",
                    )
                )
                # 各ビンのマッチコメントをホバーに
                matched_by_bin: dict[int, list[str]] = {}
                _m = matched.copy()
                _m["bin"] = (_m["time_seconds"] // bin_seconds).astype(int)
                for bin_idx, group in _m.groupby("bin"):
                    matched_by_bin[int(bin_idx)] = group.head(6)["text"].astype(str).tolist()

                search_hover = []
                for s in hit_counts["bin_start"]:
                    bin_idx = int(s // bin_seconds)
                    samples = matched_by_bin.get(bin_idx, [])
                    lines = []
                    for c in samples[:5]:
                        safe = c.replace("<", "&lt;").replace(">", "&gt;")
                        truncated = safe[:32] + ("…" if len(safe) > 32 else "")
                        lines.append(f"・{truncated}")
                    if len(samples) > 5:
                        lines.append(f"<i>… 他 {len(samples) - 5}件</i>")
                    preview = "<br>".join(lines) if lines else "<i>(無し)</i>"
                    search_hover.append([format_timestamp(s), preview])

                search_fig.add_trace(
                    go.Bar(
                        x=hit_counts["bin_start"],
                        y=hit_counts["count"],
                        name=f'"{keyword}" 出現',
                        marker=dict(color="#00d992"),
                        customdata=search_hover,
                        hovertemplate=(
                            "<b>%{customdata[0]}</b>  "
                            f"<span style='color:#00d992'>%{{y}} 件 \"{keyword}\"</span><br>"
                            "<span style='color:#8b949e;font-size:11px'>"
                            "──────────────</span><br>"
                            "%{customdata[1]}"
                            "<extra></extra>"
                        ),
                    )
                )
                search_fig.update_layout(
                    height=400,
                    margin=dict(l=40, r=20, t=20, b=40),
                    paper_bgcolor="#101010",
                    plot_bgcolor="#101010",
                    font=dict(color="#f2f2f2", family="Inter"),
                    dragmode="pan",
                    xaxis=dict(
                        title="配信秒数",
                        gridcolor="#3d3a39",
                        rangeslider=dict(
                            visible=True,
                            bgcolor="#1a1a1a",
                            bordercolor="#3d3a39",
                            borderwidth=1,
                            thickness=0.1,
                        ),
                        fixedrange=False,
                    ),
                    yaxis=dict(title="件数", gridcolor="#3d3a39", fixedrange=True),
                    legend=dict(bgcolor="#1a1a1a", bordercolor="#3d3a39"),
                    barmode="overlay",
                    hoverlabel=dict(
                        bgcolor="#1a1a1a",
                        bordercolor="#00d992",
                        font=dict(color="#f2f2f2", family="Inter", size=12),
                        align="left",
                    ),
                )
                st.plotly_chart(
                    search_fig,
                    use_container_width=True,
                    config={
                        "scrollZoom": True,
                        "displaylogo": False,
                        "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
                        "displayModeBar": "hover",
                    },
                )

                st.markdown("**ヒットしたコメント(時系列)**")
                preview = matched.head(200).copy()
                preview["時刻"] = preview["time_seconds"].apply(format_timestamp)
                st.dataframe(
                    preview[["時刻", "author", "text"]].rename(
                        columns={"author": "ユーザー", "text": "コメント"}
                    ),
                    use_container_width=True,
                    hide_index=True,
                    height=400,
                )
            else:
                st.info("該当コメントは見つかりませんでした。")

    # --- 切り抜き候補タブ ---
    with tab_peaks:
        st.markdown(f"#### ピーク上位 {len(peaks)} 件")

        summarize_btn_key = f"summarize_{bin_seconds}_{top_n}_{max_comments}"
        if st.button("ピーク帯をClaudeで要約する", key="summarize_btn", type="primary"):
            if not api_key:
                st.error("APIキー未設定です。管理者へ連絡してください。")
            else:
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

        for i, peak in enumerate(peaks):
            ts_label = format_timestamp(peak.bin_start)
            with st.expander(
                f"#{i+1}  {ts_label}  ・  {peak.count} コメント / {int(peak.bin_end - peak.bin_start)}秒",
                expanded=(i < 3),
            ):
                left, right = st.columns([2, 3])
                with left:
                    if "youtube.com" in url_for_links or "youtu.be" in url_for_links:
                        jump_url = make_youtube_timestamp_url(url_for_links, peak.bin_start)
                        st.markdown(f"[▶ {ts_label} にジャンプ]({jump_url})")
                    else:
                        st.markdown(f"**TC:** `{ts_label}`")
                    st.markdown(f"**コメント数:** {peak.count}")
                    if summaries and i < len(summaries):
                        st.markdown("**要約**")
                        st.write(summaries[i].summary)
                with right:
                    st.markdown("**代表コメント**")
                    sample = peak.messages.head(15)
                    for _, row in sample.iterrows():
                        st.text(
                            f"[{format_timestamp(row['time_seconds'])}] "
                            f"{row['author']}: {row['text']}"
                        )

        # CSVエクスポート
        if summaries:
            st.markdown("---")
            export_df = pd.DataFrame(
                {
                    "timecode": [format_timestamp(s.bin_start) for s in summaries],
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
