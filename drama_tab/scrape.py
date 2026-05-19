"""
TikTok Studio スクレイパー。

事前に `python login.py` でログイン状態を保存しておくこと。

使い方:
    python scrape.py list                 # Content画面をスクロールして全動画IDを収集
    python scrape.py analytics            # 各動画の分析データを取得
    python scrape.py analytics --limit 5  # 動作確認: 最初の5本だけ
    python scrape.py all                  # list → analytics
    python scrape.py discover             # DOM デバッグ用 (HTML/PNG ダンプ)
"""
from __future__ import annotations

import argparse
import json
import re
import string
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright, TimeoutError as PWTimeout

ROOT = Path(__file__).parent
DATA = ROOT / "data"
STORAGE_STATE = DATA / "storage_state.json"
VIDEOS_JSON = DATA / "videos.json"
DUMP_DIR = DATA / "raw_html"

STUDIO_BASE = "https://www.tiktok.com/tiktokstudio"
CONTENT_URL = f"{STUDIO_BASE}/content"
ANALYTICS_URL = STUDIO_BASE + "/analytics/{vid}"  # /tiktokstudio/analytics/<video_id>

# data-tt セレクタ (DOM ダンプから確定)
SEL_CONTENT_TABLE = '[data-tt="components_PostTable_Container"]'
SEL_HEADER_TAB_TEXT = '[data-tt="Header_HeaderTabBar_TUXText"]'
SEL_METRIC_CARD = '[data-tt="VideoOverviewPage_VideoMetricsCard_Clickable"]'
SEL_VIDEO_INFO_TEXT = '[data-tt="VideoOverviewPage_VideoInfoCard_TUXText"]'

# サイドバーは順番固定: 動画再生数, 合計時間, 平均視聴時間, 完視聴率, 新規フォロワー数
METRIC_KEYS = ["views", "total_watch_time", "avg_watch_time", "completion_rate", "new_followers"]

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def require_session() -> None:
    if not STORAGE_STATE.exists():
        sys.exit(
            f"セッションファイルが無い: {STORAGE_STATE}\n"
            f"先に `python login.py` でログインしてください。"
        )


def open_browser(headless: bool = False):
    require_session()
    p = sync_playwright().start()
    try:
        browser = p.chromium.launch(
            headless=headless,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
    except Exception as e:
        print(f"warn: channel='chrome' 起動失敗 ({e}). bundled Chromium にフォールバック")
        browser = p.chromium.launch(headless=headless)
    context = browser.new_context(
        storage_state=str(STORAGE_STATE),
        locale="ja-JP",
        viewport={"width": 1440, "height": 900},
        user_agent=CHROME_UA,
    )
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    )
    page = context.new_page()
    return p, browser, context, page


def load_videos() -> dict[str, dict]:
    if VIDEOS_JSON.exists():
        return json.loads(VIDEOS_JSON.read_text(encoding="utf-8"))
    return {}


def save_videos(videos: dict[str, dict]) -> None:
    VIDEOS_JSON.write_text(
        json.dumps(videos, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def extract_video_id(url_or_href: str | None) -> str | None:
    if not url_or_href:
        return None
    m = re.search(r"/(?:video|analytics)/(\d{15,20})", url_or_href)
    return m.group(1) if m else None


SAFE = set(string.ascii_letters + string.digits + "_-.")


def safe_label(s: str) -> str:
    out = "".join(c if c in SAFE else "_" for c in s)
    return out[:80] or "snap"


# ---------------------------------------------------------------------------
# discover: 実DOM確認用
# ---------------------------------------------------------------------------

def cmd_discover() -> None:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    p, browser, context, page = open_browser(headless=False)
    try:
        page.goto(CONTENT_URL)
        print()
        print("=" * 60)
        print("ブラウザで目的のページを表示してターミナルでラベル入力 → Enter")
        print("(ラベルは英数字_- のみOK。URL等を貼ると自動でサニタイズされる)")
        print("`quit` と入力で終了。")
        print("=" * 60)
        i = 0
        while True:
            raw = input(f"[{i}] ラベル > ").strip()
            if raw in ("quit", "q", "exit"):
                break
            label = safe_label(raw) if raw else f"snap_{i}"
            (DUMP_DIR / f"{label}.html").write_text(page.content(), encoding="utf-8")
            try:
                page.screenshot(path=str(DUMP_DIR / f"{label}.png"), full_page=True)
            except Exception as e:
                print(f"  screenshot failed: {e}")
            print(f"  saved {label}.html  url={page.url}")
            i += 1
    finally:
        browser.close()
        p.stop()


# ---------------------------------------------------------------------------
# list: Content画面をスクロールして video_id を収集
# ---------------------------------------------------------------------------

SCROLL_DIAGNOSTIC_JS = r"""
() => {
    // ページ内のスクロール可能な全要素を探して、状態を返す
    const out = [];
    document.querySelectorAll('*').forEach(el => {
        if (el.scrollHeight > el.clientHeight + 50) {
            const cs = getComputedStyle(el);
            const ov = cs.overflowY;
            if (ov === 'auto' || ov === 'scroll') {
                out.push({
                    tag: el.tagName,
                    tt: el.getAttribute('data-tt') || '',
                    cls: (el.className || '').toString().slice(0, 60),
                    scrollTop: el.scrollTop,
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                });
            }
        }
    });
    return out;
}
"""

SCROLL_FORCE_JS = r"""
(amount) => {
    // 全スクロール可能要素を amount px だけ下にスクロール
    let moved = 0;
    document.querySelectorAll('*').forEach(el => {
        if (el.scrollHeight > el.clientHeight + 50) {
            const cs = getComputedStyle(el);
            if (cs.overflowY === 'auto' || cs.overflowY === 'scroll') {
                const before = el.scrollTop;
                el.scrollBy(0, amount);
                if (el.scrollTop !== before) moved += (el.scrollTop - before);
                // wheel イベントも発火 (IntersectionObserver や onScroll 用)
                el.dispatchEvent(new WheelEvent('wheel', {deltaY: amount, bubbles: true}));
            }
        }
    });
    // window scroll も
    window.scrollBy(0, amount);
    return moved;
}
"""


def collect_ids_from_dom(page: Page) -> list[str]:
    hrefs = page.locator("a[href*='/video/']").evaluate_all(
        "els => els.map(e => e.getAttribute('href'))"
    )
    out = []
    for href in hrefs:
        vid = extract_video_id(href)
        if vid:
            out.append(vid)
    return out


def cmd_list(headless: bool = False, max_stagnant: int = 8) -> None:
    """Content画面の仮想スクロールテーブルを舐めて video_id を全部集める。"""
    p, browser, context, page = open_browser(headless=headless)
    try:
        print(f"-> {CONTENT_URL}")
        page.goto(CONTENT_URL, wait_until="domcontentloaded")
        page.wait_for_selector(SEL_CONTENT_TABLE, timeout=20000)
        page.wait_for_timeout(2500)

        try:
            total_texts = page.locator(SEL_HEADER_TAB_TEXT).all_inner_texts()
            print(f"header tabs: {total_texts}")
        except Exception:
            pass

        # スクロール可能要素を診断
        diag = page.evaluate(SCROLL_DIAGNOSTIC_JS)
        print(f"scrollable elements detected: {len(diag)}")
        for d in diag[:5]:
            print(f"  {d['tag']} tt={d['tt']!r} sh={d['scrollHeight']} ch={d['clientHeight']}")

        videos = load_videos()
        ids_before = set(videos.keys())
        stagnant = 0
        iteration = 0

        # テーブルにフォーカスして PageDown/End を使えるようにするための準備
        try:
            page.locator(SEL_CONTENT_TABLE).first.hover()
        except Exception:
            pass

        while stagnant < max_stagnant:
            iteration += 1

            # 現在DOMの ID を収集
            new = 0
            for vid in collect_ids_from_dom(page):
                if vid not in videos:
                    videos[vid] = {
                        "id": vid,
                        "studio_url": f"https://www.tiktok.com/@?/video/{vid}",
                        "analytics": None,
                    }
                    new += 1

            if new == 0:
                stagnant += 1
            else:
                stagnant = 0
                save_videos(videos)

            # 多戦略スクロール
            moved = 0
            try:
                moved = page.evaluate(SCROLL_FORCE_JS, 1800) or 0
            except Exception as e:
                print(f"  JS scroll error: {e}")

            # マウスホイールも併用 (テーブル上にホバーしてから)
            try:
                page.locator(SEL_CONTENT_TABLE).first.hover()
                page.mouse.wheel(0, 1500)
            except Exception:
                pass

            # キーボード PageDown (フォーカスがテーブル内にあれば効く)
            try:
                page.keyboard.press("PageDown")
            except Exception:
                pass

            print(f"[scroll {iteration:>3}] total={len(videos)} (+{new})  moved={moved}px  stagnant={stagnant}/{max_stagnant}")
            page.wait_for_timeout(1500)

        save_videos(videos)
        added = len(set(videos.keys()) - ids_before)
        print(f"\n完了: {len(videos)} 件の動画ID (今回 +{added})")
        print(f"出力: {VIDEOS_JSON}")
    finally:
        browser.close()
        p.stop()


# ---------------------------------------------------------------------------
# analytics: 各動画の分析データを取得
# ---------------------------------------------------------------------------

def extract_metric_value(card) -> str | None:
    try:
        return card.locator(".absolute-value").first.inner_text(timeout=2000).strip()
    except Exception:
        return None


def extract_current_video(page: Page) -> dict[str, Any]:
    info_texts: list[str] = []
    try:
        info_texts = page.locator(SEL_VIDEO_INFO_TEXT).all_inner_texts()
    except Exception:
        pass
    title = info_texts[0].strip() if len(info_texts) > 0 else None
    post_date_raw = info_texts[1].strip() if len(info_texts) > 1 else None

    metrics: dict[str, str | None] = {k: None for k in METRIC_KEYS}
    cards = page.locator(SEL_METRIC_CARD)
    n = cards.count()
    for i in range(min(n, len(METRIC_KEYS))):
        metrics[METRIC_KEYS[i]] = extract_metric_value(cards.nth(i))

    return {
        "title": title,
        "post_date_raw": post_date_raw,
        "metrics": metrics,
        "url": page.url,
    }


def cmd_analytics(limit: int | None = None, headless: bool = False, refresh: bool = False) -> None:
    videos = load_videos()
    if not videos:
        sys.exit(f"先に `python scrape.py list` を実行してください ({VIDEOS_JSON} が空)")

    targets = [
        v for v in videos.values()
        if refresh or not v.get("analytics") or not v["analytics"].get("metrics", {}).get("views")
    ]
    if limit:
        targets = targets[:limit]
    print(f"対象: {len(targets)} 件 (total: {len(videos)})")

    p, browser, context, page = open_browser(headless=headless)
    try:
        for idx, v in enumerate(targets, 1):
            url = ANALYTICS_URL.format(vid=v["id"])
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector(SEL_METRIC_CARD, timeout=15000)
                page.wait_for_timeout(1200)  # 数値レンダ余裕
                data = extract_current_video(page)
                v["analytics"] = data
                v["scraped_at"] = int(time.time())
                videos[v["id"]] = v
                save_videos(videos)
                ms = data["metrics"]
                print(f"[{idx:>4}/{len(targets)}] {v['id']}  {data['title']!r:<30}  "
                      f"views={ms['views']} comp={ms['completion_rate']} avg={ms['avg_watch_time']}")
            except PWTimeout:
                print(f"[{idx:>4}/{len(targets)}] {v['id']}  TIMEOUT (skip)")
            except Exception as e:
                print(f"[{idx:>4}/{len(targets)}] {v['id']}  ERROR: {e}")
            page.wait_for_timeout(800)  # 礼節としての小休止
    finally:
        browser.close()
        p.stop()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover", help="DOMダンプ (デバッグ用)")
    l = sub.add_parser("list", help="Content画面をスクロールして全動画IDを収集")
    l.add_argument("--headless", action="store_true")
    l.add_argument("--max-stagnant", type=int, default=8,
                   help="新IDが0件続いたら停止する回数 (default: 8)")
    a = sub.add_parser("analytics", help="各動画の分析データを取得")
    a.add_argument("--limit", type=int, default=None, help="最大件数 (動作確認用)")
    a.add_argument("--headless", action="store_true")
    a.add_argument("--refresh", action="store_true", help="取得済みも再取得")
    sub.add_parser("all", help="list → analytics 連続実行")
    args = parser.parse_args()

    if args.cmd == "discover":
        cmd_discover()
    elif args.cmd == "list":
        cmd_list(headless=args.headless, max_stagnant=args.max_stagnant)
    elif args.cmd == "analytics":
        cmd_analytics(limit=args.limit, headless=args.headless, refresh=args.refresh)
    elif args.cmd == "all":
        cmd_list()
        cmd_analytics()


if __name__ == "__main__":
    main()
