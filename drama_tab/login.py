"""
TikTok Studio に手動ログインしてセッションを保存するワンタイムスクリプト。

TikTok は Playwright の Chromium を BOT 検知してログインを弾くので、
このスクリプトは「あなたの普通の Chrome を debug port 付きで起動して、
そこに Playwright を後から接続する(CDP attach)」方式を使う。

使い方:
    cd drama_tab
    python login.py

スクリプトが自動で Chrome を起動するので、開いた Chrome で TikTok Studio に
QR / ID パスなど通常通りログインする。ダッシュボードが見えたらこのターミナルで
Enter を押す → data/storage_state.json に Cookie 等が保存される。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from shutil import which

from playwright.sync_api import sync_playwright

STUDIO_URL = "https://www.tiktok.com/tiktokstudio"
STORAGE_STATE = Path(__file__).parent / "data" / "storage_state.json"
CDP_PORT = 9222
PROFILE_DIR = Path(os.environ.get("TEMP", ".")) / "chrome_for_tiktok"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser(prefer: str = "chrome") -> str | None:
    cands = CHROME_CANDIDATES if prefer == "chrome" else EDGE_CANDIDATES
    for p in cands:
        if Path(p).exists():
            return p
    # PATH fallback
    return which("chrome.exe") or which("msedge.exe")


def launch_chrome(chrome_path: str) -> subprocess.Popen:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        chrome_path,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        STUDIO_URL,
    ]
    print(f"起動: {chrome_path}")
    print(f"  port = {CDP_PORT}")
    print(f"  profile = {PROFILE_DIR}")
    return subprocess.Popen(args)


def attach_and_save() -> None:
    STORAGE_STATE.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
        contexts = browser.contexts
        if not contexts:
            sys.exit("ERROR: Chrome の context が見つからない。タブが少なくとも1つ開いている必要がある。")
        context = contexts[0]
        # TikTok 関連のタブを優先して状態を保存
        tiktok_pages = [pg for pg in context.pages if "tiktok.com" in pg.url]
        if tiktok_pages:
            print(f"TikTok タブ発見: {tiktok_pages[0].url}")
        else:
            print("warn: TikTok タブが見当たらないが、context 全体の Cookie を保存する")
        context.storage_state(path=str(STORAGE_STATE))
        print(f"\nセッション保存: {STORAGE_STATE}")
        # 接続を切るだけで Chrome 自体は閉じない(ユーザーが手動で閉じる)
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser",
        choices=["chrome", "edge"],
        default="chrome",
        help="使うブラウザ。Chrome が無ければ edge を試す",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Chrome を自動起動しない(既に手動で port 9222 起動済みの場合)",
    )
    args = parser.parse_args()

    proc: subprocess.Popen | None = None
    if not args.no_launch:
        path = find_browser(args.browser)
        if not path and args.browser == "chrome":
            print("Chrome が見つからない。Edge を試します。")
            path = find_browser("edge")
        if not path:
            sys.exit(
                "Chrome / Edge どちらも見つからない。\n"
                f"手動で Chrome を起動してから --no-launch で再実行してください:\n"
                f'  & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
                f'--remote-debugging-port={CDP_PORT} --user-data-dir="$env:TEMP\\chrome_for_tiktok"'
            )
        proc = launch_chrome(path)
        time.sleep(2.0)  # 起動待ち

    print()
    print("=" * 60)
    print("起動した Chrome で TikTok Studio に普通にログインしてください。")
    print("(QR / ID パス / 2FA など好きな方法で)")
    print("ダッシュボードが見えたら、このターミナルで Enter を押す。")
    print("=" * 60)
    input("ログイン完了したら Enter > ")

    attach_and_save()

    print()
    print("OK. 次は: python scrape.py discover")
    print("(起動した Chrome ウィンドウは閉じて構いません)")


if __name__ == "__main__":
    main()
