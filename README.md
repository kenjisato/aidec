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

```
uv run aidec brief 2027            # 今日の授業・締め切り・相談・準備の候補（--evening で明日）
uv run aidec supervise             # instructor-kit の上位コマンド（通常は直接呼ばない）
```

## 導入

```
uv tool install git+https://github.com/kenjisato/aidec
```

- `data_dir` は絶対パス（`~` は可）。相対パスはエラーになる。
- instructor-kit から使うには `~/.config/instructor-kit/supervisor.yaml` に書く。

  ```yaml
  command: [aidec, supervise]
  protocol: 1
  ```

- `ghq` が PATH に無い環境では、環境変数 `AIDEC_GHQ_ROOT` に ghq のルートを指定する。
