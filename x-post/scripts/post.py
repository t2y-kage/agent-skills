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


def normalize_body(text: str) -> str:
    # モデルがリテラルで書きがちなエスケープ列を、実際の制御文字へ。
    # 順序に注意: \r\n を先に処理してから \n を処理する。
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    return text.strip()


parser = argparse.ArgumentParser(description="post a tweet, optionally as a reply (thread) or a quote")
parser.add_argument("text", help="tweet body")
group = parser.add_mutually_exclusive_group()
group.add_argument("--reply-to", dest="reply_to", default=None,
                   help="tweet ID to reply to (continues a thread)")
group.add_argument("--quote", dest="quote", default=None,
                   help="tweet ID to quote")
parser.add_argument("--quote-author", dest="quote_author", default=None,
                    help="screen name of the quoted tweet's author (for the log)")
parser.add_argument("--poll-option", dest="poll_options", action="append", default=None,
                    help="poll choice (repeat 2-4 times, each <= 25 chars)")
parser.add_argument("--poll-hours", dest="poll_hours", type=int, default=24,
                    help="poll duration in hours (1-168, default 24)")
args = parser.parse_args()

text = normalize_body(args.text)
if not text:
    sys.exit("usage: post.py [--reply-to <tweet_id>] <text>")

reply_to = args.reply_to.strip() if args.reply_to else None
if reply_to and not reply_to.isdigit():
    sys.exit(f"invalid --reply-to tweet id: {reply_to}")

quote = args.quote.strip() if args.quote else None
if quote and not quote.isdigit():
    sys.exit(f"invalid --quote tweet id: {quote}")

poll_options = [o.strip() for o in args.poll_options] if args.poll_options else None
if poll_options:
    if args.reply_to or args.quote:
        sys.exit("--poll-option cannot be combined with --reply-to or --quote")
    if not (2 <= len(poll_options) <= 4):
        sys.exit(f"poll needs 2-4 options, got {len(poll_options)}")
    too_long = [o for o in poll_options if len(o) > 25 or not o]
    if too_long:
        sys.exit(f"poll options must be 1-25 chars: {too_long}")
    if len(set(poll_options)) != len(poll_options):
        sys.exit("poll options must be unique")
    if not (1 <= args.poll_hours <= 168):
        sys.exit(f"--poll-hours must be 1-168, got {args.poll_hours}")

client = tweepy.Client(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)

try:
    if reply_to:
        resp = client.create_tweet(text=text, in_reply_to_tweet_id=reply_to)
    elif quote:
        resp = client.create_tweet(text=text, quote_tweet_id=quote)
    elif poll_options:
        resp = client.create_tweet(text=text, poll_options=poll_options,
                                   poll_duration_minutes=args.poll_hours * 60)
    else:
        resp = client.create_tweet(text=text)
    tid = resp.data["id"]
    url = f"https://x.com/i/status/{tid}"
    # 投稿ログ（日付つき1行。返信のときは4列目に reply_to=<id> を付ける）
    logp = pathlib.Path(__file__).resolve().parent.parent / "posted.log"
    line = f"{datetime.date.today().isoformat()}\t{url}\t{text}"
    if reply_to:
        line += f"\treply_to={reply_to}"
    elif quote:
        line += f"\tquote={quote}"
        if args.quote_author:
            line += f"\tquote_author={args.quote_author.lstrip('@')}"
    elif poll_options:
        line += "\tpoll=" + "|".join(poll_options)
    with logp.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"OK {url}")
except Exception as e:
    sys.exit(f"post failed: {e}")
