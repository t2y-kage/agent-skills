import argparse
import json
import os
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
    description="fetch home timeline as JSON lines (quote-post candidates)")
parser.add_argument("--limit", type=int, default=30,
                    help="max number of timeline posts to fetch (5-100, default 30)")
args = parser.parse_args()

limit = max(5, min(args.limit, 100))

client = tweepy.Client(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)

try:
    me = client.get_me(user_auth=True)
    my_id = me.data.id

    resp = client.get_home_timeline(
        max_results=limit,
        exclude=["retweets", "replies"],
        tweet_fields=["created_at", "public_metrics", "referenced_tweets", "lang"],
        expansions=["author_id"],
        user_fields=["username", "name"],
        user_auth=True,
    )
except Exception as e:
    sys.exit(f"fetch failed: {e}")

users = {}
if resp.includes and "users" in resp.includes:
    users = {u.id: u for u in resp.includes["users"]}

count = 0
for t in resp.data or []:
    # 自分の投稿は引用候補にしない
    if t.author_id == my_id:
        continue
    # リツイートはAPI側で除外済みだが、引用リツイートの入れ子は避ける
    if t.referenced_tweets and any(r.type == "quoted" for r in t.referenced_tweets):
        continue
    u = users.get(t.author_id)
    m = t.public_metrics or {}
    print(json.dumps({
        "id": str(t.id),
        "author": u.username if u else "",
        "name": u.name if u else "",
        "text": t.text,
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "likes": m.get("like_count", 0),
        "reposts": m.get("retweet_count", 0),
    }, ensure_ascii=False))
    count += 1

if count == 0:
    print("no candidates", file=sys.stderr)
