# agent-skills

X（x.com）と Slack をつなぐエージェントスキル群。
各スキルは `SKILL.md` と、必要なら `scripts/` を持つ独立したディレクトリになっている。

## スキル一覧

| スキル | 役割 | 情報の向き |
|---|---|---|
| [x-post](x-post/SKILL.md) | Slack の話題を公開情報へ一般化して x.com へ投稿する。いいねとリポストによる反応も行う | Slack → x.com |
| [x-read](x-read/SKILL.md) | タイムラインを読んでダイジェストを作る。指定アカウントやポストへの返信案を提案する（読み取り専用） | x.com → 会話 |
| [x-discussion](x-discussion/SKILL.md) | 議論を一次資料から追跡し、主張と批判と争点を出典付きで整理して Slack へ還元する（読み取り専用） | x.com → Slack |

x-read と x-discussion はどちらも x.com を読むが、成果物が違う。
ダイジェストと返信案までが x-read、議論の経緯と争点の整理が x-discussion である。

## 前提

python3、tweepy、X API の環境変数 4 つ（`X_API_KEY`、`X_API_SECRET`、`X_ACCESS_TOKEN`、`X_ACCESS_TOKEN_SECRET`）がローカルで使えることを前提とする。
環境構築の手順はこのリポジトリでは扱わない。

## `{baseDir}` の読み替え

SKILL.md 内のコマンドは `{baseDir}` を使って書かれている。
これはスキルランタイムが解決するプレースホルダなので、シェルへそのまま貼っても動かない。
ローカルで実行するときは、そのスキルのディレクトリに読み替える。

```sh
# SKILL.md の記述
python3 {baseDir}/scripts/fetch_timeline.py --mode home --limit 30

# ローカルで実行するとき（リポジトリ直下から）
python3 x-read/scripts/fetch_timeline.py --mode home --limit 30
```

x-discussion は隣接する x-read のスクリプトを `{baseDir}/../x-read/scripts/...` として参照する。
このため x-read と x-discussion が同じ親ディレクトリに置かれていることが前提になる。

## ログの形式

各スキルは実行履歴をタブ区切りのログに残す。
重複の回避と件数の計数に使う運用データだが、スキルが実際に何を出力するかの例にもなるので、`posted.log`、`read.log`、`suggest.log` はリポジトリに含めている。
`reacted.log` と `work/` 配下は追跡しない。

| ファイル | 列 | 用途 |
|---|---|---|
| `x-post/posted.log` | 日付、ポスト URL、投稿本文、`reply_to=<ID>` または `quote=<ID>` または `poll=<選択肢>\|<選択肢>`（`quote=` のときは 5 列目に `quote_author=<名前>`） | 日次上限の計数、重複の回避、スレッド展開と自己引用の候補選定 |
| `x-post/reacted.log` | `like=<ID>` または `retweet=<ID>` | いいねとリポストの重複防止 |
| `x-read/read.log` | 日付、ポスト ID、テーマの短い要約 | ダイジェストの既読管理 |
| `x-read/suggest.log` | 日付、ポスト ID、返信案の短い要約 | 返信提案の重複防止 |
| `work/<slug>/sent.log` | 日付、チャンネル ID、起点 ts、seq、メッセージ ts | x-discussion の Slack 送信台帳。未送信分からの再開に使う |

`posted.log` の 3 列目には投稿本文がそのまま入る。
複数行の投稿を行うとログの 1 行に収まらず、後続の行は 1 列だけの継続行になる。
このため x-post/SKILL.md の候補選定に使う awk（`$4 == ""` で元投稿を選ぶもの）は、継続行を正しく扱えない。
現状は継続行が日付の比較で落ちるため実害は出ていないが、本文に改行を含めて投稿すると候補選定の対象が想定より狭くなる。

## ローカルでの検証

### 1. SKILL.md の静的確認（API 不要）

コマンド例に書かれたスクリプトが実在するか、cwd に依存する相対パスが混じっていないかを確かめる。
どちらも出力が空なら問題ない。

```sh
# {baseDir} 起点のパスが実在するかを確かめる
# （config.local のように .example だけを配る運用設定は除外する）
for f in */SKILL.md; do
  d=$(dirname "$f")
  grep -oE '\{baseDir\}[^ `"'"'"')]*' "$f" | sort -u | while read -r p; do
    r="${p/\{baseDir\}/$d}"
    [ -e "$r" ] || [ -e "$r.example" ] || echo "missing: $f -> $p"
  done
done

# cwd 依存の相対パスでスクリプトを呼んでいないかを確かめる
# （`{baseDir}/../x-read/...` は起点が決まっているので対象外。markdown のリンクも対象外）
grep -nE '(^|[ `("])\.\.?/[^ )`"]*\.(py|sh)' */SKILL.md
```

### 2. 取得スクリプトの疎通確認（X API を 1 リクエスト消費）

```sh
python3 x-read/scripts/fetch_timeline.py --mode post --id <既知の公開ポストID>
```

JSON が 1 行返れば取得経路が生きている。
`--mode post` は 1 リクエストで済むので、home や search より確認の負担が小さい。

### 3. x-discussion の通し確認（Slack へは送らない）

既知の議論を 1 本選び、x-discussion スキルを節 1 から節 5 まで実行させ、`work/<slug>/thread.md` の生成で止める。
生成された原稿について次を確かめる。

```sh
# 区切りが root と reply 1/N から N/N まで連番で揃っているか
grep -n '^=== ' work/<slug>/thread.md

# Slack で展開されない記法が混じっていないか（出力が空ならよい）
grep -nE '^\||\[[^]]+\]\([^)]+\)' work/<slug>/thread.md
```

残りは目視で確認する。
各返信にその主張に対応する出典 URL があるか、起点がタイトルと背景 1〜2 文と参照 2〜3 件に収まっているかを見る。

## 作業ディレクトリ

x-discussion は調査ごとの成果物を `work/<slug>/` に置く。
`thread.md`（Slack へ送る原稿の全文）と `sent.log`（送信台帳）が入る。
このディレクトリは追跡しない。
