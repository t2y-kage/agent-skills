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
    description="fetch recent mentions (replies/quotes to us) as JSON lines")
parser.add_argument("--limit", type=int, default=20,
                    help="max number of mentions to fetch (5-100, default 20)")
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

    resp = client.get_users_mentions(
        id=my_id,
        max_results=limit,
        tweet_fields=["created_at", "referenced_tweets", "lang", "conversation_id"],
        expansions=["author_id", "referenced_tweets.id"],
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
    # 自分自身のメンション（自己リプライ等）は反応対象にしない
    if t.author_id == my_id:
        continue
    # 返信か引用かを判定（通常メンションも含めて kind を付ける）
    kind = "mention"
    if t.referenced_tweets:
        types = {r.type for r in t.referenced_tweets}
        if "replied_to" in types:
            kind = "reply"
        elif "quoted" in types:
            kind = "quote"
    u = users.get(t.author_id)
    print(json.dumps({
        "id": str(t.id),
        "kind": kind,
        "author": u.username if u else "",
        "name": u.name if u else "",
        "text": t.text,
        "created_at": t.created_at.isoformat() if t.created_at else "",
    }, ensure_ascii=False))
    count += 1

if count == 0:
    print("no mentions", file=sys.stderr)
