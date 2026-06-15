import argparse
import datetime
import os
import pathlib
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

parser = argparse.ArgumentParser(description="react to a tweet by liking or reposting")
parser.add_argument("action", choices=["like", "retweet"], help="reaction type")
parser.add_argument("tweet_id", help="target tweet ID")
args = parser.parse_args()

tweet_id = args.tweet_id.strip()
if not tweet_id.isdigit():
    sys.exit(f"invalid tweet id: {tweet_id}")

# 重複防止: 同じ (action, id) を既に記録済みなら何もしない
logp = pathlib.Path(__file__).resolve().parent.parent / "reacted.log"
marker = f"{args.action}={tweet_id}"
if logp.exists():
    with logp.open(encoding="utf-8") as f:
        if any(marker in line.strip().split("\t") for line in f):
            print(f"SKIP already {args.action}: {tweet_id}")
            sys.exit(0)

client = tweepy.Client(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)

try:
    if args.action == "like":
        client.like(tweet_id)
    else:
        client.retweet(tweet_id)
    with logp.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.date.today().isoformat()}\t{marker}\n")
    print(f"OK {args.action} {tweet_id}")
except Exception as e:
    sys.exit(f"{args.action} failed: {e}")
