"""TikTok Drama Analytics Dashboard。

使い方:
    cd drama_tab
    streamlit run app.py

データ配置:
    drama_tab/data/
      Overview_*/Overview.csv
      Content_*/Content.csv            (任意)
      Viewers_*/Viewers.csv
      Followers_*/FollowerHistory.csv, FollowerGender.csv, ...
      videos.json                       (scrape.py の出力)

CSV はサブフォルダに入っていても自動探索される。
videos.json が空でも CSV ベースのダッシュボードは動く。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from loaders import DATA_DIR_DEFAULT, StudioData, load_all
from series import attach_series_columns


# ---------------------------------------------------------------------------
# 共通ヘルパ
# ---------------------------------------------------------------------------

def short_title(s: str, n: int = 40) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def humanize(v: float | None) -> str:
    if v is None or pd.isna(v):
        return "-"
    v = float(v)
    if abs(v) >= 1e6:
        return f"{v/1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"{v/1e3:.1f}K"
    return f"{v:,.0f}"


def humanize_seconds(s: float | None) -> str:
    if s is None or pd.isna(s):
        return "-"
    s = float(s)
    if s >= 3600:
        h = s // 3600
        m = (s % 3600) // 60
        return f"{int(h)}h{int(m)}m"
    if s >= 60:
        return f"{int(s // 60)}m{int(s % 60)}s"
    return f"{s:.1f}s"


@st.cache_data(ttl=30)
def cached_load(data_dir: str) -> StudioData:
    d = load_all(Path(data_dir))
    d.videos = attach_series_columns(d.videos)
    return d


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="TikTok Drama Analytics", layout="wide", page_icon="🎬")

# Sidebar
st.sidebar.title("🎬 Drama Analytics")
data_dir = st.sidebar.text_input("データフォルダ", str(DATA_DIR_DEFAULT))
if st.sidebar.button("🔄 再読み込み", use_container_width=True):
    cached_load.clear()
st.sidebar.caption(
    "CSV(Overview/Viewers/Followers) と scrape.py 出力の videos.json をここから読みます。"
)

try:
    data = cached_load(data_dir)
except Exception as e:
    st.error(f"データ読み込みエラー: {e}")
    st.stop()

videos = data.videos

# ---------------------------------------------------------------------------
# 上部の KPI
# ---------------------------------------------------------------------------

st.title("🎬 TikTok Drama Analytics")

c1, c2, c3, c4, c5 = st.columns(5)

if data.overview is not None and not data.overview.empty:
    total_views_365 = int(data.overview["Video Views"].sum())
    c1.metric("総再生数 (365d CSV)", humanize(total_views_365))
else:
    c1.metric("総再生数", "-")

if data.follower_history is not None and not data.follower_history.empty:
    latest = data.follower_history.iloc[-1]
    delta = int(data.follower_history["Difference in followers from previous day"].sum())
    c2.metric("フォロワー (現在)", humanize(int(latest["Followers"])), delta=f"+{humanize(delta)} (365d)")
else:
    c2.metric("フォロワー", "-")

c3.metric("スクレイプ済動画", f"{data.n_videos_scraped} / {data.n_videos_total}",
          help="data/videos.json 内で analytics が取得済みの本数")

if not videos.empty:
    avg_comp = videos["completion_rate"].mean()
    c4.metric("平均完視聴率", f"{avg_comp:.1f}%" if not pd.isna(avg_comp) else "-")
    avg_watch = videos["avg_watch_time_sec"].mean()
    c5.metric("平均視聴時間", humanize_seconds(avg_watch))
else:
    c4.metric("平均完視聴率", "-")
    c5.metric("平均視聴時間", "-")

# スクレイプ進行中のバナー
if 0 < data.n_videos_scraped < data.n_videos_total:
    pct = data.n_videos_scraped / data.n_videos_total
    st.progress(pct, text=f"スクレイプ進行中: {data.n_videos_scraped}/{data.n_videos_total} ({pct*100:.1f}%)")

if data.n_videos_total == 0:
    st.info(
        "videos.json がまだありません。`python scrape.py list` → `python scrape.py analytics` で動画データを収集してください。"
        "CSV のみのダッシュボードは下のタブで見れます。"
    )

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_overview, tab_videos, tab_series, tab_audience, tab_data = st.tabs(
    ["📊 概要", "🎬 動画一覧", "📚 シリーズ別", "👥 視聴者属性", "🛠 データ"]
)


# ---------- Tab: 概要 ----------
with tab_overview:
    if data.overview is None:
        st.warning("Overview.csv が見つかりません。データフォルダを確認してください。")
    else:
        df = data.overview.copy()
        date_min, date_max = df["date"].min(), df["date"].max()
        st.caption(f"期間: {date_min.date()} 〜 {date_max.date()}")

        ms = ["Video Views", "Profile Views", "Likes", "Comments", "Shares"]
        chosen = st.multiselect("表示メトリクス", ms, default=["Video Views", "Profile Views"])

        fig = go.Figure()
        for m in chosen:
            fig.add_trace(go.Scatter(x=df["date"], y=df[m], name=m, mode="lines"))
        fig.update_layout(height=400, hovermode="x unified", legend_orientation="h")
        st.plotly_chart(fig, use_container_width=True)

        # 月別集計
        st.subheader("月別サマリー")
        df_m = df.copy()
        df_m["month"] = df_m["date"].dt.to_period("M").astype(str)
        agg = df_m.groupby("month")[["Video Views", "Profile Views", "Likes", "Comments", "Shares"]].sum()
        st.dataframe(agg.style.format("{:,.0f}"), use_container_width=True)

    # フォロワー推移
    if data.follower_history is not None:
        st.subheader("フォロワー推移")
        fh = data.follower_history
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=fh["date"], y=fh["Followers"], name="フォロワー数", line=dict(color="#1f77b4")))
        fig.add_trace(
            go.Bar(
                x=fh["date"],
                y=fh["Difference in followers from previous day"],
                name="増減",
                marker_color="rgba(255,127,14,0.4)",
                yaxis="y2",
            )
        )
        fig.update_layout(
            height=350,
            yaxis=dict(title="フォロワー数"),
            yaxis2=dict(title="増減", overlaying="y", side="right"),
            hovermode="x unified",
            legend_orientation="h",
        )
        st.plotly_chart(fig, use_container_width=True)


# ---------- Tab: 動画一覧 ----------
with tab_videos:
    if videos.empty:
        st.info("スクレイプ済の動画がまだありません。`python scrape.py analytics` の進行を待ってください。")
    else:
        st.caption(f"{len(videos)} 件の動画")

        # フィルタ
        f_col1, f_col2, f_col3 = st.columns([1, 1, 2])
        min_views = f_col1.number_input("最小再生数", 0, value=0, step=1000)
        min_comp = f_col2.number_input("最小完視聴率(%)", 0.0, 100.0, 0.0, step=1.0)
        sort_by = f_col3.selectbox(
            "並び順",
            ["completion_rate (desc)", "views (desc)", "avg_watch_time_sec (desc)",
             "new_followers (desc)", "post_date (desc)"]
        )

        v = videos[
            (videos["views"] >= min_views)
            & (videos["completion_rate"].fillna(0) >= min_comp)
        ].copy()
        col, asc = sort_by.split(" ")[0], sort_by.endswith("(asc)")
        v = v.sort_values(col, ascending=asc, na_position="last")

        # 散布図: 完視聴率 × 再生数
        st.subheader("完視聴率 × 再生数 (バブル=新規フォロワー)")
        scat = v.dropna(subset=["completion_rate", "views"]).copy()
        if not scat.empty:
            scat["title_short"] = scat["title"].map(lambda t: short_title(t, 60))
            scat["nf_size"] = scat["new_followers"].fillna(1).clip(lower=1)
            fig = px.scatter(
                scat,
                x="completion_rate",
                y="views",
                size="nf_size",
                hover_data={"title_short": True, "views": ":,.0f", "completion_rate": ":.1f",
                            "avg_watch_time_sec": ":.1f", "new_followers": ":,.0f",
                            "series": True, "nf_size": False},
                color="series",
                log_y=True,
                labels={"completion_rate": "完視聴率 (%)", "views": "再生数 (log)"},
            )
            fig.update_layout(height=500, legend_orientation="v")
            st.plotly_chart(fig, use_container_width=True)

        # テーブル
        st.subheader("動画一覧")
        view_df = pd.DataFrame({
            "post_date": v["post_date"].dt.strftime("%Y-%m-%d") if "post_date" in v else "",
            "series": v["series"],
            "ep": v["episode"].fillna(v["episode_guess"]),
            "title": v["title"].map(lambda t: short_title(t, 60)),
            "views": v["views"],
            "completion_%": v["completion_rate"],
            "avg_watch(s)": v["avg_watch_time_sec"],
            "total_watch(h)": v["total_watch_time_sec"].apply(
                lambda s: round(s / 3600, 1) if pd.notna(s) else None
            ),
            "new_followers": v["new_followers"],
            "url": v["url"],
        })
        st.dataframe(
            view_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "views": st.column_config.NumberColumn(format="%d"),
                "completion_%": st.column_config.NumberColumn(format="%.1f"),
                "avg_watch(s)": st.column_config.NumberColumn(format="%.1f"),
                "new_followers": st.column_config.NumberColumn(format="%d"),
                "url": st.column_config.LinkColumn(display_text="Studio"),
            },
        )


# ---------- Tab: シリーズ別 ----------
with tab_series:
    if videos.empty or videos["series"].isna().all():
        st.info("シリーズ抽出可能な動画がまだありません(タイトルに `== シリーズ名 ==` 形式が必要)。")
    else:
        # シリーズ別サマリー
        s_agg = videos.dropna(subset=["series"]).groupby("series").agg(
            episodes=("id", "count"),
            total_views=("views", "sum"),
            avg_views=("views", "mean"),
            avg_completion=("completion_rate", "mean"),
            avg_watch_sec=("avg_watch_time_sec", "mean"),
            total_new_followers=("new_followers", "sum"),
        ).sort_values("total_views", ascending=False)

        st.subheader("シリーズ別サマリー")
        st.dataframe(
            s_agg.style.format({
                "total_views": "{:,.0f}",
                "avg_views": "{:,.0f}",
                "avg_completion": "{:.1f}%",
                "avg_watch_sec": "{:.1f}s",
                "total_new_followers": "{:,.0f}",
            }),
            use_container_width=True,
        )

        # シリーズ選択 → EP順の推移
        series_list = s_agg.index.tolist()
        chosen_series = st.multiselect("シリーズを選択して EP 推移を見る", series_list,
                                        default=series_list[: min(3, len(series_list))])
        if chosen_series:
            sub = videos[videos["series"].isin(chosen_series)].copy()
            # EP順 (episode 列 → 無ければ episode_guess → 無ければ post_date)
            sub["ep_order"] = sub["episode"].fillna(sub["episode_guess"])
            sub = sub.sort_values(["series", "ep_order", "post_date"])
            sub["ep_seq"] = sub.groupby("series").cumcount() + 1

            c1, c2 = st.columns(2)
            with c1:
                fig = px.line(
                    sub, x="ep_seq", y="views", color="series",
                    markers=True, hover_data=["title", "completion_rate"],
                    labels={"ep_seq": "EP順", "views": "再生数"},
                    log_y=True,
                )
                fig.update_layout(height=400, title="EP順の再生数 (log) — 離脱率の代替指標")
                st.plotly_chart(fig, use_container_width=True)

            with c2:
                fig = px.line(
                    sub, x="ep_seq", y="completion_rate", color="series",
                    markers=True, hover_data=["title", "views"],
                    labels={"ep_seq": "EP順", "completion_rate": "完視聴率 (%)"},
                )
                fig.update_layout(height=400, title="EP順の完視聴率")
                st.plotly_chart(fig, use_container_width=True)


# ---------- Tab: 視聴者属性 ----------
with tab_audience:
    cols = st.columns(2)

    with cols[0]:
        if data.follower_gender is not None and not data.follower_gender.empty:
            st.subheader("性別")
            fig = px.pie(data.follower_gender, names="Gender", values="Distribution", hole=0.4)
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)

    with cols[1]:
        if data.follower_territories is not None and not data.follower_territories.empty:
            st.subheader("国別")
            ft = data.follower_territories.sort_values("Distribution", ascending=False)
            fig = px.bar(ft, x="Top territories", y="Distribution",
                         labels={"Distribution": "比率"})
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)

    if data.viewers is not None and not data.viewers.empty:
        st.subheader("新規視聴者 vs リピーター (日次)")
        vw = data.viewers
        fig = go.Figure()
        fig.add_trace(go.Bar(x=vw["date"], y=vw["New Viewers"], name="新規", marker_color="#1f77b4"))
        fig.add_trace(go.Bar(x=vw["date"], y=vw["Returning Viewers"], name="リピーター",
                              marker_color="#ff7f0e"))
        fig.update_layout(barmode="stack", height=350, hovermode="x unified", legend_orientation="h")
        st.plotly_chart(fig, use_container_width=True)

    if data.follower_activity is not None and not data.follower_activity.empty:
        st.subheader("時間帯ヒートマップ (フォロワーのアクティブ時間)")
        fa = data.follower_activity
        pivot = fa.pivot_table(index="date", columns="Hour", values="Active followers", aggfunc="mean")
        if not pivot.empty:
            fig = px.imshow(
                pivot.values,
                labels=dict(x="Hour", y="Date", color="Active"),
                x=list(pivot.columns),
                y=[d.strftime("%m/%d") for d in pivot.index],
                aspect="auto",
                color_continuous_scale="Viridis",
            )
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)
            st.caption("TikTok仕様で直近7日 × 24時間 のみ取得可能。投稿のベストタイミング判断に。")


# ---------- Tab: データ ----------
with tab_data:
    st.subheader("ロード結果")
    summary = {
        "Overview": "✓" if data.overview is not None else "✕",
        "Viewers": "✓" if data.viewers is not None else "✕",
        "FollowerHistory": "✓" if data.follower_history is not None else "✕",
        "FollowerActivity": "✓" if data.follower_activity is not None else "✕",
        "FollowerGender": "✓" if data.follower_gender is not None else "✕",
        "FollowerTopTerritories": "✓" if data.follower_territories is not None else "✕",
        "videos.json": f"{data.n_videos_scraped}/{data.n_videos_total}",
    }
    st.json(summary)
    st.caption(f"起点年: {data.start_year}")

    if not videos.empty:
        st.subheader("videos.json 生データ (先頭20)")
        st.dataframe(videos.head(20), use_container_width=True)
