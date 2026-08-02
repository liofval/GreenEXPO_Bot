# GREEN×EXPO 2027 通知bot

2027年横浜で開催される **GREEN×EXPO 2027（国際園芸博覧会）** に関する
ニュースを LINE でお届けするbotです。

## 📲 友だち追加

[![LINE Add Friend](https://scdn.line-apps.com/n/line_add_friends/btn/ja.png)](https://lin.ee/WwPsXPR)

**➡️ https://lin.ee/WwPsXPR**

タップして友だち追加するだけで、明日の朝から通知が届きます。

---

## 何が届くか

### ☀️ 毎朝9時 (JST): GREEN×EXPO 関連ニュース

Google News に載る GREEN×EXPO 2027 関連の全記事から、以下の観点でスコアリングして上位を通知:

| マーカー | 意味 |
|---|---|
| 📰 | 神奈川・横浜のローカルメディア（神奈川新聞、tvk、FMヨコハマ、ヨコハマ経済新聞、新横浜新聞、Circular Yokohama、タウンニュース等） |
| 🏢 | 企業の関与ニュース（協賛・スポンサー・パビリオン・コラボ・提携・出展・新技術） |

### 📢 公式サイト更新 (1時間ごと)

[expo2027yokohama.or.jp](https://expo2027yokohama.or.jp/) のお知らせページを毎時5分に巡回。
新しいプレスリリース・お知らせが出たらすぐに通知します。

### 🐦 X下書き付き

通知の末尾には「そのままXに貼れる下書き」が最大3件付きます。
140字本文 + URL + ハッシュタグ (`#GreenExpo2027 #国際園芸博覧会 #横浜`)。

---

## 収集ソース

- **Google News RSS** — 15クエリで検索
  - `"GREEN×EXPO 2027"`, `"国際園芸博覧会 2027"`, `"横浜 花博 2027"`,
    `"上瀬谷 万博"`, `"GREEN×EXPO協会"`, `"AIPH 2027"`,
    `"Yokohama Expo 2027"`, `"Horticultural Expo 2027"` ほか
- **公式サイト** (expo2027yokohama.or.jp/news/) — スクレイピングで差分検知

## 動作環境

- Python 3.12 (GitHub Actions側) / 3.13 (ローカル)
- GitHub Actions cron
  - `daily-notify.yml`: 毎日 00:00 UTC (= 09:00 JST)
  - `official-poll.yml`: 毎時5分

## セットアップ (開発者向け)

```bash
# 依存インストール
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt

# ローカルで動作確認
.venv/bin/python bot/main.py --dry-run --mode both
```

デプロイには GitHub Secret `LINE_CHANNEL_ACCESS_TOKEN` (LINE Messaging APIの長期トークン) が必要です。
