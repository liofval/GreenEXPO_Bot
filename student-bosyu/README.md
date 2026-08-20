# student-bosyu

Web広く **企画スタッフ・登壇・ハッカソン枠の募集** を検知して Slack に通知する bot。
かつては PR TIMES 一本だったが、方針転換で以下のような「中に入って動ける枠」を主軸に。

## 何を拾うか

| タグ | カテゴリ | 例 |
|---|---|---|
| 🛠 | 企画スタッフ | SPIKES in IVS、SUSHITECH ITAMAE、運営メンバー募集 |
| 🧠 | ハッカソン | ハッカソン / アイデアソン / デザインジャム 参加者・メンター |
| 🎤 | ピッチ登壇 | ピッチコンテスト登壇者、スピーカー、パネリスト募集 |
| 🎪 | イベント運営 | イベントスタッフ、運営ボランティア |
| 🏫 | 学生団体 | 学生実行委員、学生アンバサダー |
| 💼 | インターン | 長期/サマー/有給インターン |
| 🏆 | コンテスト | 学生対象/若手対象のコンテスト、アワード |

GreenExpo/横浜/サステナ関連キーワードでスコアボーナス（既存プロジェクトの狙いに沿わせる）。
運営母体の **X / Instagram の公式アカウント** を記事本文/リンクから自動抽出して通知に同梱。

## 除外

以下はノイズとして除外:
- 就活・新卒/中途採用系（`新卒採用`, `26卒` 等）
- 正社員/業務委託の求人
- 商品文脈（`学生服`, `学割`, `学生証`）
- 教員募集

## データ源

| ソース | 手段 | 備考 |
|---|---|---|
| Google News RSS | クエリ複数投げ | `site:x.com` クエリで X の投稿もカバー |
| connpass | 公式API (v1/event/) | APIキー不要 |
| Peatix | 検索ページHTMLスクレイピング | 構造変更で壊れる可能性あり |

## フィルタ仕組み

1. **Layer 1 (gate)**: `keywords.TARGET_TERMS`（学生・若者・クリエイター等）と `keywords.RECRUIT_TERMS`（募集・登壇・ハッカソン等）を **両方含む** ものだけ通す
2. **Layer 2 (score)**: `POSITIVE_KEYWORDS` で加点、`EXCLUDE_KEYWORDS` にヒットしたら除外
3. スコア閾値 `SCORE_THRESHOLD=4` 以上を通知

キーワードは `student-bosyu/keywords.py` に集約。運用しながら随時調整する前提。

## 通知先

Slack Incoming Webhook（`SLACK_WEBHOOK_URL_BOSYU` secret）で1チャンネルに投稿。
Block Kit で:
- カテゴリ / 主催者 / どのソースから拾ったか（via Google/connpass/Peatix）
- タイトル + リンク
- 抜粋（200字）
- マッチキーワード + score
- **運営SNSアカウント (X / Instagram)** — 記事から抽出できたときのみ

## 実行環境

- GitHub Actions cron: 毎時15分（`.github/workflows/student-bosyu-poll.yml`）
- 状態: `student-bosyu/state.json`（60日で剪定、workflow が自動 commit）
- 独立 `concurrency` グループ（`greenexpo-notify` とは別）

## セットアップ (開発者向け)

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r student-bosyu/requirements.txt

# ローカル dry-run（Slack投稿せず標準出力に一覧表示）
.venv/bin/python student-bosyu/main.py --dry-run --no-save

# 合成データで Slack ペイロードだけをテスト
.venv/bin/python student-bosyu/main.py --test
```

## GitHub Secrets

- `SLACK_WEBHOOK_URL_BOSYU`: Slack Incoming Webhook URL
