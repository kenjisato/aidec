---
name: intake
description: Use when the user tells a schedule item or request by mouth, in the session whose working directory is the aidec data_dir — 「〇日に会議が入った」「出張が決まった」「学会がある」「事務から〇〇を△日までにと頼まれた」「締め切りが入った」「RA に頼みたい」.
---

# intake

利用者が伝えた予定や依頼を、種類を見分けて置くべき場所に置く。

## 最初に: 場所の確認

作業ディレクトリの git toplevel が、設定の `data_dir` と同じか調べる。`data_dir` は `$AIDEC_CONFIG`、無ければ `~/.config/aidec/config.yaml` のキー `data_dir`（`~` は展開し、実パスで比べる）。違えば「授業の外のことは workdesk のセッションで聞いてください」と言って終わる。

## 種類と置き場

- 日付のある予定（会議、出張、副業、学会）、締め切りのある長い仕事（研究、授業準備、運営）: `<data_dir>/<年度>/events.yaml` に 1 行足す。年度は 4 月始まり
  `- {date: YYYY-MM-DD, end: YYYY-MM-DD, kind: trip|side_job|conference|meeting|deadline, title: ..., note: ..., prep: 2w}`（`end`、`note`、`prep` は任意）
  授業の日の事実になるのは trip / side_job / conference だけ
- 30 分で終わる小さな仕事、RA への依頼: 利用者のタスク管理（task-manage スキルがあればその手順）に渡す。タスク管理への書き込みはその手順だけが行う
- Google カレンダー: 利用者が明示して頼んだときだけ

## 上がってきた相談を閉じる

授業から上がってきた相談（`inbox/<ref>.md`）が決まったら、`inbox/done/<ref>.md` に移してコミットする（確認してから）。`inbox/done/` は一覧に出ない。

休講・補講・日付の移動が決まったら、`<data_dir>/<年度>/moves.yaml` に 1 行足し（見せてから）、`aidec issue <年度> --course <id>` で配る。
`- {course: <id>, n: 7, date: YYYY-MM-DD, ref: <ref>}`（移す）か `- {course: <id>, n: 7, cancelled: true, ref: <ref>}`（補講しない）。`notes` は任意。
`aidec issue` は授業レポの作業ツリーに `schedule.yaml` を書くだけで、コミットは授業の側（director）がする。そのことを利用者に一言伝える。

## 手順

1. 種類を決め、足す行（または task-manage に渡す内容）を利用者に見せて、OK をもらってから書く。曖昧な日付や題は推測せず聞く
2. `events.yaml` に書いたら、データのレポでコミットする
3. 授業に当たりそうなら `aidec week <年度> --table --days <日数>` で、どの授業のどの回かを示し、`aidec issue` がその回の事実として載せることを伝える。オンライン・オンデマンドは授業の側で決める。休講・補講・移動は授業から相談が上がってから決める（上の「上がってきた相談を閉じる」）。ここでは先に決めない
