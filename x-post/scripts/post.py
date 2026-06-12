import datetime
import os
import pathlib
import sys

try:
    import tweepy
except ModuleNotFoundError:
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "tweepy"], check=True)
    import tweepy

REQUIRED = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
missing = [k for k in REQUIRED if not os.environ.get(k)]
if missing:
    sys.exit(f"missing env vars: {', '.join(missing)}")

if len(sys.argv) < 2 or not sys.argv[1].strip():
    sys.exit("usage: post.py <text>")

def normalize_body(text: str) -> str:
    # モデルがリテラルで書きがちなエスケープ列を、実際の制御文字へ。
    # 順序に注意: \r\n を先に処理してから \n を処理する。
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    return text.strip()

text = normalize_body(sys.argv[1])

client = tweepy.Client(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)

try:
    resp = client.create_tweet(text=text)
    tid = resp.data["id"]
    url = f"https://x.com/i/status/{tid}"
    # 投稿ログ（日付つき1行）
    logp = pathlib.Path(__file__).resolve().parent.parent / "posted.log"
    with logp.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.date.today().isoformat()}\t{url}\t{text}\n")
    print(f"OK {url}")
except Exception as e:
    sys.exit(f"post failed: {e}")
