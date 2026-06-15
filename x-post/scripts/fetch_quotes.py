import argparse
import datetime
import json
import os
import pathlib
import re
import sys

try:
    import tweepy
except ModuleNotFoundError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "tweepy"], check=True)
    import tweepy

REQUIRED = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
missing = [k for k in REQUIRED if not os.environ.get(k)]
if missing:
    sys.exit(f"missing env vars: {', '.join(missing)}")

parser = argparse.ArgumentParser(
    description="fetch quote posts of our own tweets as JSON lines")
parser.add_argument("--tweet-id", dest="tweet_ids", action="append", default=None,
                    help="explicit own tweet ID to check (repeatable). Overrides --recent/--days.")
parser.add_argument("--recent", type=int, default=5,
                    help="check the N most recent own root posts from posted.log (default 5)")
parser.add_argument("--days", type=int, default=None,
                    help="check own root posts within the last D days (exclusive with --recent)")
parser.add_argument("--max-per-tweet", type=int, default=20,
                    help="max quotes fetched per tweet (5-100, default 20)")
parser.add_argument("--limit", type=int, default=50,
                    help="overall cap on emitted quotes (default 50)")
args = parser.parse_args()

if args.days is not None and any(a in sys.argv for a in ("--recent",)):
    sys.exit("--days and --recent are mutually exclusive")

STATUS_RE = re.compile(r"status/(\d+)")
logp = pathlib.Path(__file__).resolve().parent.parent / "posted.log"


def own_root_ids_from_log():
    """posted.log から自分のルート投稿（返信・引用・アンケート行を除く）のIDを新しい順に返す。
    各行: 日付<TAB>URL<TAB>本文[<TAB>reply_to=.. | quote=.. | poll=.. ]
    4列目が存在する行は reply/quote/poll なのでルート投稿ではない。"""
    rows = []
    if not logp.exists():
        return rows
    with logp.open(encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            if len(parts) >= 4 and parts[3]:
                continue  # reply / quote / poll 行は対象外
            m = STATUS_RE.search(parts[1])
            if not m:
                continue
            rows.append((parts[0], m.group(1)))  # (date, id)
    rows.reverse()  # 新しい順
    return rows


# 対象の自分の投稿IDを決める
if args.tweet_ids:
    target_ids = [t.strip() for t in args.tweet_ids if t.strip().isdigit()]
    if not target_ids:
        sys.exit("no valid --tweet-id given")
else:
    rows = own_root_ids_from_log()
    if args.days is not None:
        cutoff = (datetime.date.today() - datetime.timedelta(days=args.days)).isoformat()
        target_ids = [tid for (d, tid) in rows if d >= cutoff]
    else:
        target_ids = [tid for (_, tid) in rows[:max(1, args.recent)]]
    if not target_ids:
        print("no target posts in posted.log", file=sys.stderr)
        sys.exit(0)

max_per = max(5, min(args.max_per_tweet, 100))

client = tweepy.Client(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)

emitted = 0
seen = set()  # 同じ引用ツイートを複数回出さない
for own_id in target_ids:
    if emitted >= args.limit:
        break
    try:
        resp = client.get_quote_tweets(
            id=own_id,
            max_results=max_per,
            tweet_fields=["created_at", "lang"],
            expansions=["author_id"],
            user_fields=["username", "name"],
            user_auth=True,
        )
    except Exception as e:
        print(f"fetch failed for {own_id}: {e}", file=sys.stderr)
        continue

    users = {}
    if resp.includes and "users" in resp.includes:
        users = {u.id: u for u in resp.includes["users"]}

    for t in resp.data or []:
        if emitted >= args.limit:
            break
        if str(t.id) in seen:
            continue
        seen.add(str(t.id))
        u = users.get(t.author_id)
        print(json.dumps({
            "id": str(t.id),
            "kind": "quote",
            "author": u.username if u else "",
            "name": u.name if u else "",
            "text": t.text,
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "quoted_post": own_id,
        }, ensure_ascii=False))
        emitted += 1

if emitted == 0:
    print("no quotes", file=sys.stderr)
