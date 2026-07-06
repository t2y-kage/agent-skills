import argparse
import json
import os
import sys

try:
    import tweepy
except ModuleNotFoundError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "tweepy"], check=True)
    # インストール先（ユーザー site）が起動時に存在しなかった場合に備えて再走査する
    import importlib
    import site
    site.main()
    importlib.invalidate_caches()
    import tweepy

parser = argparse.ArgumentParser(
    description="fetch posts as JSON lines (digest candidates)")
parser.add_argument("--mode", choices=["home", "search", "user", "post"], default="home",
                    help="home: reverse-chronological home timeline / "
                         "search: recent search (last 7 days, incl. accounts not followed) / "
                         "user: recent original posts of a specific account / "
                         "post: specific posts by ID, with quoted/replied-to context")
parser.add_argument("--query",
                    help="search query for --mode search, e.g. '(\"Claude Code\" OR #ClaudeCode) -is:reply'. "
                         "retweets are excluded automatically")
parser.add_argument("--user", action="append",
                    help="target username for --mode user (with or without leading @). "
                         "repeat the option to fetch multiple accounts at once")
parser.add_argument("--id", action="append",
                    help="target post ID for --mode post. repeat the option for multiple posts")
parser.add_argument("--lang", default="ja",
                    help="language filter for --mode search (default: ja). "
                         "pass 'all' to disable. ignored if the query already contains a lang: operator")
parser.add_argument("--limit", type=int, default=30,
                    help="max number of posts to output after filtering (1-100, default 30); "
                         "in user mode the limit applies per account. "
                         "the API always fetches one page of 100 posts regardless of this value")
args = parser.parse_args()

if args.mode == "search" and not args.query:
    parser.error("--query is required for --mode search")
if args.mode == "user" and not args.user:
    parser.error("--user is required for --mode user")
if args.mode == "post" and not args.id:
    parser.error("--id is required for --mode post")

REQUIRED = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
missing = [k for k in REQUIRED if not os.environ.get(k)]
if missing:
    sys.exit(f"missing env vars: {', '.join(missing)}")

limit = max(1, min(args.limit, 100))

# レートリミットは 15 分あたりのリクエスト数で数えられるため、
# 1 ページの取得件数は常に最大の 100 件とし、出力側で limit に切り詰める
PAGE_SIZE = 100

client = tweepy.Client(
    consumer_key=os.environ["X_API_KEY"],
    consumer_secret=os.environ["X_API_SECRET"],
    access_token=os.environ["X_ACCESS_TOKEN"],
    access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
)

TWEET_FIELDS = ["created_at", "public_metrics", "referenced_tweets", "lang"]
USER_FIELDS = ["username", "name"]

# タイムライン系モード（home / search / user）の共通パラメータ
TIMELINE_FIELDS = dict(
    tweet_fields=TWEET_FIELDS,
    expansions=["author_id"],
    user_fields=USER_FIELDS,
    user_auth=True,
)


def included_users(resp):
    return {u.id: u for u in (resp.includes or {}).get("users", [])}


def to_obj(t, users):
    """全モード共通の出力 JSON 形式"""
    u = users.get(t.author_id)
    m = t.public_metrics or {}
    return {
        "id": str(t.id),
        "author": u.username if u else "",
        "name": u.name if u else "",
        "text": t.text,
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "likes": m.get("like_count", 0),
        "reposts": m.get("retweet_count", 0),
    }


if args.mode == "post":
    # GET /2/tweets — 指定ポストを引用元・返信先の文脈つきで取得する。
    # ID で明示指定されたものをそのまま返すので、他モードのフィルタや limit は適用しない
    try:
        resp = client.get_tweets(
            ids=args.id,
            tweet_fields=TWEET_FIELDS,
            expansions=["author_id", "referenced_tweets.id", "referenced_tweets.id.author_id"],
            user_fields=USER_FIELDS,
            user_auth=True,
        )
    except Exception as e:
        sys.exit(f"fetch failed: {e}")

    # 削除済み・非公開などで取得できなかった ID は stderr に出す
    for err in resp.errors or []:
        print(f"not available: {err.get('value', '')} ({err.get('title', '')})", file=sys.stderr)
    if not resp.data:
        sys.exit("no posts found")

    users = included_users(resp)
    ref_tweets = {t.id: t for t in (resp.includes or {}).get("tweets", [])}
    REF_KEYS = {"quoted": "quoted", "replied_to": "in_reply_to", "retweeted": "retweeted"}
    for t in resp.data:
        obj = to_obj(t, users)
        for r in t.referenced_tweets or []:
            rt = ref_tweets.get(r.id)
            if rt is not None and r.type in REF_KEYS:
                obj[REF_KEYS[r.type]] = to_obj(rt, users)
        print(json.dumps(obj, ensure_ascii=False))
    sys.exit(0)

try:
    me = client.get_me(user_auth=True)
    my_id = me.data.id

    # 1 レスポンス = 1 出力グループ。limit はグループごとに適用する
    # （user モードで複数アカウントを指定しても、各アカウントに limit 件の枠を保証する）
    resps = []
    if args.mode == "home":
        # GET /2/users/:id/timelines/reverse_chronological
        resps.append(client.get_home_timeline(
            max_results=PAGE_SIZE,
            exclude=["retweets", "replies"],
            **TIMELINE_FIELDS,
        ))
    elif args.mode == "search":
        # GET /2/tweets/search/recent
        query = args.query
        if "is:retweet" not in query:
            query += " -is:retweet"
        if args.lang != "all" and "lang:" not in query:
            query += f" lang:{args.lang}"
        resps.append(client.search_recent_tweets(
            query=query,
            max_results=PAGE_SIZE,
            **TIMELINE_FIELDS,
        ))
    else:
        # GET /2/users/by → GET /2/users/:id/tweets（アカウントごとに 1 リクエスト）
        usernames = list(dict.fromkeys(u.lstrip("@") for u in args.user))
        found = client.get_users(usernames=usernames, user_auth=True)
        by_name = {u.username.lower(): u for u in (found.data or [])}
        for name in usernames:
            target = by_name.get(name.lower())
            if target is None:
                print(f"user not found: {name}", file=sys.stderr)
                continue
            resps.append(client.get_users_tweets(
                id=target.id,
                max_results=PAGE_SIZE,
                exclude=["retweets", "replies"],
                **TIMELINE_FIELDS,
            ))
        if not resps:
            sys.exit("no valid users")
except Exception as e:
    sys.exit(f"fetch failed: {e}")

total = 0
for resp in resps:
    users = included_users(resp)
    count = 0
    for t in resp.data or []:
        # 自分の投稿はダイジェスト候補にしない
        if t.author_id == my_id:
            continue
        # API 側の exclude=["retweets"] をすり抜けるリツイートがあるため、テキストでも除外する
        if t.text.startswith("RT @"):
            continue
        # 引用リツイートの入れ子は避ける
        if t.referenced_tweets and any(r.type == "quoted" for r in t.referenced_tweets):
            continue
        print(json.dumps(to_obj(t, users), ensure_ascii=False))
        count += 1
        total += 1
        if count >= limit:
            break

if total == 0:
    print("no candidates", file=sys.stderr)
