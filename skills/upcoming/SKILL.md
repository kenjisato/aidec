---
name: upcoming
description: Use when the user asks what is coming up — 「今後の予定」「来週何がある？」「今後3週間の予定表」「予定を見せて」「この先の授業と準備」 — in the session whose working directory is the aidec data_dir.
---

# upcoming

今日から数週間分の授業・準備の日・締め切り・上がってきた相談を、一覧にして見せる。

## 最初に: 場所の確認

作業ディレクトリの git toplevel が、設定の `data_dir` と同じか調べる。`data_dir` は `$AIDEC_CONFIG`、無ければ `~/.config/aidec/config.yaml` のキー `data_dir`（`~` は展開し、実パスで比べる）。違えば「授業の外のことは workdesk のセッションで聞いてください」と言って終わる。

## 実行（Bash 1 回で済ませる）

年度は 4 月始まり（2026-10 なら 2026、2027-02 も 2026）。日数は頼まれた週数 × 7（指定が無ければ 21）。

```bash
aidec week <年度> --table --days <日数> ; aidec check <年度>
```

`--table` は今日から日ごとの表を出し、何も無い日も 1 行出す。`check` は問題があると終了コード 1 になるが、それは失敗ではない。

## 見せ方

- 表はそのままコードブロックに入れて見せる。行をまとめたり、何も無い日を落としたりしない（空き時間が大事な情報である）
- 「(not issued)」は、その授業にまだ `schedule.yaml` を配っていないという意味。日付は学事暦から計算したもので正しい
- 「休講（未決）」は、授業の側が休講を上げていて、まだ決まっていない回。決めたら intake の手順で `moves.yaml` に書いて配る
- `check` の行は表の後に「気になる点」として短く添える。「（注意）」の付いたもの（研究日など）は知らせるだけでよい
- 準備の重さは判断しない。並べるだけにする
- 本業の見積り時間は書かない
- 上がってきた相談は、決まったら inbox/done/ に移してコミットする（確認してから）
- 略称は `courses.yaml` の `label`。新しい略称が要るときは、データのレポで決めて `label` に書く
