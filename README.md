# 配信コメントアクティブ率 可視化 & 切り抜き候補抽出

YouTube Live / Twitch のアーカイブ配信から、コメントの盛り上がりをグラフ化し、Claude APIで各ピーク帯を自動要約するStreamlitアプリ。切り抜き動画の選定用途を想定。

## 使い方(編集者向け)

1. 配布されたURLにアクセス → パスワード入力
2. **YouTubeの場合**: 「URLから取得」を選んでURL貼り付け → 「解析する」
3. **Twitchの場合**:
   1. ローカルで `TwitchDownloaderCLI.exe chatdownload --id <VOD_ID> -o chat.json`
   2. アプリで「ローカルJSONをアップロード」を選んで `chat.json` をD&D
4. グラフが出たら「ピーク帯をClaudeで要約する」ボタンで自動要約
5. CSVダウンロードで切り抜き候補リスト書き出し

## ローカル開発

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env  # ANTHROPIC_API_KEY を書く
streamlit run app.py
```

## Streamlit Cloud デプロイ

1. このリポジトリをGitHubにpush
2. [share.streamlit.io](https://share.streamlit.io/) で New app → リポジトリ選択 → `app.py` 指定
3. デプロイ後、Settings → Secrets で以下を貼る:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   APP_PASSWORD = "編集者と共有するパスワード"
   ```
4. デプロイ完了URLとパスワードを編集者に共有

## ファイル構成

- `app.py` — Streamlit UI
- `chat_fetcher.py` — YouTube(yt-dlp) / Twitch(JSON) チャット取得
- `analyzer.py` — 秒単位ビン + ピーク検出
- `summarizer.py` — Claude API による要約(モデルは `claude-sonnet-4-6`)
