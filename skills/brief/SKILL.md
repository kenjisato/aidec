---
name: brief
description: Use when the user asks what today or tomorrow looks like, in the session whose working directory is the aidec data_dir — 「今日の予定」「明日は何をする」「朝の確認」「今夜のうちに明日の確認」「今日の授業は」「明日進める準備は」.
---

# brief

今日（または明日）の授業、近い締め切り、急ぎの相談、明日進める授業準備の候補を知らせる。

## 最初に: 場所の確認

作業ディレクトリの git toplevel が、設定の `data_dir` と同じか調べる。`data_dir` は `$AIDEC_CONFIG`、無ければ `~/.config/aidec/config.yaml` のキー `data_dir`（`~` は展開し、実パスで比べる）。違えば「授業の外のことは workdesk のセッションで聞いてください」と言って終わる。授業レポでは授業の外のことを扱わないため。

## 手順

1. `aidec brief <年度>` を実行する。夜に明日を聞かれたら `--evening`、日付の指定は `--date YYYY-MM-DD`。年度は 4 月始まり（2026-10 なら 2026、2027-02 も 2026）
2. 利用者のタスク管理（task-manage スキルがあればその手順）で、その日の分を一覧にして添える（コマンドはここに写さない）
3. 結果をまとめて見せる

## 見せ方

- 準備の候補は「候補」として、理由（授業日が近い、受け入れが未了、会議や出張で時間が少ない）と並べる。決めるのは利用者。何を先にやるべきかは言わない
- 上がってきた相談は、決まったら inbox/done/ に移してコミットする（確認してから）
- 時間の見積りは書かない
- 授業レポの clone は fetch していない。手元が古いかもしれないことを一言添える
