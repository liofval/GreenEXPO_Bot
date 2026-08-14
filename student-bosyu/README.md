# student-bosyu

PR TIMES から **学生向け募集** を検知して Slack に通知する bot。

## 何を拾うか

以下4カテゴリのプレスリリースを対象:

| タグ | カテゴリ | 例 |
|---|---|---|
| 🏫 | 学生団体・学生プロジェクト | 学生実行委員募集、学生アンバサダー |
| 🎪 | イベント運営スタッフ | 運営ボランティア、イベントスタッフ |
| 💼 | 学生インターン | 長期/サマー/有給インターン |
| 🏆 | コンテスト・アワード | 学生対象コンテスト、コンペ |

GreenExpo/横浜/サステナ関連キーワードでスコアボーナス（既存プロジェクトの狙いに沿わせる）。

## 除外

以下はノイズとして除外:
- 就活・新卒/中途採用系（`新卒採用`, `就活サービス`, `26卒` 等）
- 正社員/業務委託の求人（`エンジニア募集(正社員)` 等）
- 商品文脈（`学生服`, `学割`, `学生証`）
- 教員募集

## データ源

**PR TIMES RSS**: <https://prtimes.jp/index.rdf>

全プレスリリースが載る公式RSS。1日 200〜500件流れる中から2段フィルタで絞る。

## フィルタ仕組み

1. **Layer 1 (gate)**: `keywords.TARGET_TERMS`（学生・大学生等）と `keywords.RECRUIT_TERMS`（募集・応募等）を **両方含む** ものだけ通す
2. **Layer 2 (score)**: `POSITIVE_KEYWORDS` で加点、`EXCLUDE_KEYWORDS` にヒットしたら除外
3. スコア閾値 `SCORE_THRESHOLD=3` 以上を通知

キーワードは `student-bosyu/keywords.py` に集約。運用しながら随時調整する前提。

## 通知先

Slack Incoming Webhook（`SLACK_WEBHOOK_URL_BOSYU` secret）で1チャンネルに投稿。
Block Kit で会社名/タイトル/抜粋/マッチキーワード/スコアを整形。

## 実行環境

- GitHub Actions cron: 毎時15分（`.github/workflows/student-bosyu-poll.yml`）
- 状態: `student-bosyu/state.json`（60日で剪定、workflow が自動 commit）
- 独立 `concurrency` グループ（`greenexpo-notify` とは別）

## セットアップ (開発者向け)

```bash
# 依存インストール
python3.13 -m venv .venv
.venv/bin/pip install -r student-bosyu/requirements.txt

# ローカル dry-run（Slack投稿せず標準出力に一覧表示）
.venv/bin/python student-bosyu/main.py --dry-run --no-save
```

## GitHub Secrets

- `SLACK_WEBHOOK_URL_BOSYU`: Slack Incoming Webhook URL
