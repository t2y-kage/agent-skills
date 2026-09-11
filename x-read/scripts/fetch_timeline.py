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
parser.add_argument("--include-replies", action="store_true",
                    help="include replies in --mode user (default: excluded). "
                         "use it to follow what an account said in other people's threads")
parser.add_argument("--raw", action="store_true",
                    help="keep our own posts and quote posts in timeline modes, which are "
                         "dropped by default. use it when tracking a whole discussion, where "
                         "criticism often takes the form of a quote")
args = parser.parse_args()

if args.mode == "search" and not args.query:
    parser.error("--query is required for --mode search")
if args.mode == "user" and not args.user:
    parser.error("--user is required for --mode user")
if args.mode == "post" and not args.id:
    parser.error("--id is required for --mode post")
if args.include_replies and args.mode != "user":
    parser.error("--include-replies is only valid for --mode user")

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

TWEET_FIELDS = ["created_at", "public_metrics", "referenced_tweets", "lang",
                "conversation_id", "entities", "note_tweet", "attachments",
                "edit_history_tweet_ids"]
USER_FIELDS = ["username", "name"]
MEDIA_FIELDS = ["type", "url", "alt_text"]

# タイムライン系モード（home / search / user）の共通パラメータ
TIMELINE_FIELDS = dict(
    tweet_fields=TWEET_FIELDS,
    expansions=["author_id", "attachments.media_keys"],
    user_fields=USER_FIELDS,
    media_fields=MEDIA_FIELDS,
    user_auth=True,
)


def included_users(resp):
    return {u.id: u for u in (resp.includes or {}).get("users", [])}


def included_media(resp):
    return {m.media_key: m for m in (resp.includes or {}).get("media", [])}


def full_text(t):
    """280 字を超えるポストは text が切り詰められるため、note_tweet があればそちらを使う"""
    note = getattr(t, "note_tweet", None)
    if isinstance(note, dict) and note.get("text"):
        return note["text"]
    return t.text


def url_entities(t):
    """本文中の URL エンティティ。長文ポストは note_tweet 側にしか入らない"""
    note = getattr(t, "note_tweet", None)
    for src in (note.get("entities") if isinstance(note, dict) else None,
                getattr(t, "entities", None)):
        if isinstance(src, dict):
            for u in src.get("urls") or []:
                yield u


def expanded_urls(t):
    """t.co を展開した URL。自分自身を指すものは長文の続きか添付への内部リンクなので除く"""
    out = []
    for u in url_entities(t):
        url = u.get("expanded_url") or u.get("url")
        if url and f"/status/{t.id}" not in url:
            out.append(url)
    return list(dict.fromkeys(out))


def attached_media(t, media):
    """添付された画像・動画。図やスライドが主張の本体であることがあるので URL まで返す"""
    out = []
    for key in (getattr(t, "attachments", None) or {}).get("media_keys") or []:
        m = media.get(key)
        if m is None:
            continue
        item = {"type": m.type}
        for attr in ("url", "alt_text"):
            if getattr(m, attr, None):
                item[attr] = getattr(m, attr)
        out.append(item)
    return out


def to_obj(t, users, media):
    """全モード共通の出力 JSON 形式"""
    u = users.get(t.author_id)
    m = t.public_metrics or {}
    obj = {
        "id": str(t.id),
        "author": u.username if u else "",
        "name": u.name if u else "",
        "text": full_text(t),
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "likes": m.get("like_count", 0),
        "reposts": m.get("retweet_count", 0),
    }
    # 以下は情報があるときだけ足す。ダイジェスト用途の出力を無駄に膨らませないため
    conv = getattr(t, "conversation_id", None)
    if conv and str(conv) != str(t.id):
        # このポストが属する会話の根。返信を辿るときはこの ID を conversation_id 検索に使う
        obj["conversation_id"] = str(conv)
    urls = expanded_urls(t)
    if urls:
        obj["urls"] = urls
    att = attached_media(t, media)
    if att:
        obj["media"] = att
    edits = getattr(t, "edit_history_tweet_ids", None) or []
    if len(edits) > 1:
        # 編集のたびに新しい ID が作られる。同じ本文が複数 ID で見つかる原因
        obj["edit_history"] = [str(i) for i in edits]
    return obj


if args.mode == "post":
    # GET /2/tweets — 指定ポストを引用元・返信先の文脈つきで取得する。
    # ID で明示指定されたものをそのまま返すので、他モードのフィルタや limit は適用しない
    try:
        resp = client.get_tweets(
            ids=args.id,
            tweet_fields=TWEET_FIELDS,
            expansions=["author_id", "referenced_tweets.id", "referenced_tweets.id.author_id",
                        "attachments.media_keys"],
            user_fields=USER_FIELDS,
            media_fields=MEDIA_FIELDS,
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
    media = included_media(resp)
    ref_tweets = {t.id: t for t in (resp.includes or {}).get("tweets", [])}
    REF_KEYS = {"quoted": "quoted", "replied_to": "in_reply_to", "retweeted": "retweeted"}
    for t in resp.data:
        obj = to_obj(t, users, media)
        for r in t.referenced_tweets or []:
            rt = ref_tweets.get(r.id)
            if rt is not None and r.type in REF_KEYS:
                obj[REF_KEYS[r.type]] = to_obj(rt, users, media)
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
                exclude=["retweets"] if args.include_replies else ["retweets", "replies"],
                **TIMELINE_FIELDS,
            ))
        if not resps:
            sys.exit("no valid users")
except Exception as e:
    sys.exit(f"fetch failed: {e}")

total = 0
for resp in resps:
    users = included_users(resp)
    media = included_media(resp)
    count = 0
    for t in resp.data or []:
        # API 側の exclude=["retweets"] をすり抜けるリツイートがあるため、テキストでも除外する
        if t.text.startswith("RT @"):
            continue
        # --raw では下の 2 つを外す。議論の追跡では自分の投稿も引用による批判も落としたくない
        if not args.raw:
            # 自分の投稿はダイジェスト候補にしない
            if t.author_id == my_id:
                continue
            # 引用リツイートの入れ子は避ける
            if t.referenced_tweets and any(r.type == "quoted" for r in t.referenced_tweets):
                continue
        print(json.dumps(to_obj(t, users, media), ensure_ascii=False))
        count += 1
        total += 1
        if count >= limit:
            break

if total == 0:
    print("no candidates", file=sys.stderr)
