# aidec

個人の秘書道具。授業の予定の一覧、朝の知らせ、instructor-kit の授業レポを見て回る上位コマンドを `aidec` 一本で提供する。
データ（学事暦・授業の一覧・依頼など）はこのレポに置かず、別の非公開レポに置く。

## 設定

データのレポの場所を `~/.config/aidec/config.yaml` に書く（`AIDEC_CONFIG` でファイルを替えられる）。

```yaml
data_dir: ~/ghq/github.com/example/desk-data
```

`data_dir` が無い、またはディレクトリが無いときは、読んだファイルのパスを添えてエラーになる。

## 使い方

```
uv run aidec week 2027
uv run aidec issue 2027 --dry-run
uv run aidec check 2027
```
