---
name: intake
description: Use when 佐藤 tells a schedule item or request by mouth, in the session whose working directory is the aidec data_dir — 「〇日に会議が入った」「出張が決まった」「学会がある」「事務から〇〇を△日までにと頼まれた」「締め切りが入った」「RA に頼みたい」.
---

# intake

佐藤が伝えた予定や依頼を、種類を見分けて置くべき場所に置く。

## 最初に: 場所の確認

作業ディレクトリの git toplevel が、設定の `data_dir` と同じか調べる。`data_dir` は `$AIDEC_CONFIG`、無ければ `~/.config/aidec/config.yaml` のキー `data_dir`（`~` は展開し、実パスで比べる）。違えば「授業の外のことは workdesk のセッションで聞いてください」と言って終わる。

## 種類と置き場

- 日付のある予定（会議、出張、副業、学会）、締め切りのある長い仕事（研究、授業準備、運営）: `<data_dir>/<年度>/events.yaml` に 1 行足す。年度は 4 月始まり
  `- {date: YYYY-MM-DD, end: YYYY-MM-DD, kind: trip|side_job|conference|meeting|deadline, title: ..., note: ..., prep: 2w}`（`end`、`note`、`prep` は任意）
  授業の日の事実になるのは trip / side_job / conference だけ
- 30 分で終わる小さな仕事、RA への依頼: task-manage スキルに渡す。lontano に書くのは task-manage だけ
- Google カレンダー: 佐藤が明示して頼んだときだけ

## 手順

1. 種類を決め、足す行（または task-manage に渡す内容）を佐藤に見せて、OK をもらってから書く。曖昧な日付や題は推測せず聞く
2. `events.yaml` に書いたら、データのレポでコミットする
3. 授業に当たりそうなら `aidec week <年度> --table --days <日数>` で、どの授業のどの回かを示し、`aidec issue` がその回の事実として載せることを伝える。その回をどう行うか（休講、補講、オンラインなど）は授業の側で決める。ここでは決めない
