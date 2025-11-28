from atproto import Client
import os
import time
from datetime import datetime, timedelta, timezone

# === CONFIG ===
LIST_URI = "at://did:plc:jaka644beit3x4vmmg6yysw7/app.bsky.graph.list/3m3iga6wnmz2p"
HOURS_BACK = 5          # tijdvenster (nu 5 uur)
MAX_PER_RUN = 100       # max reposts per run
MAX_PER_USER = 3        # max per account
REPOST_LOG_FILE = "reposted_bg.txt"  # eigen log voor beautygroup
DELAY_SECONDS = 2       # vertraging tussen reposts

def log(msg: str) -> None:
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

def parse_time(record, post):
    """Probeer een bruikbare datetime te vinden voor de post."""
    for attr in ["createdAt", "indexedAt", "created_at", "timestamp"]:
        val = getattr(record, attr, None) or getattr(post, attr, None)
        if val:
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except Exception:
                continue
    return None

def main():
    username = os.getenv("BSKY_USERNAME_BG")
    password = os.getenv("BSKY_PASSWORD_BG")

    if not username or not password:
        log("ERROR: BSKY_USERNAME_BG of BSKY_PASSWORD_BG ontbreekt.")
        return

    client = Client()
    client.login(username, password)
    log("✅ Ingelogd.")

    # Reeds gereposte URIs inladen
    done = set()
    if os.path.exists(REPOST_LOG_FILE):
        with open(REPOST_LOG_FILE, "r", encoding="utf-8") as f:
            done = set(line.strip() for line in f if line.strip())

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)

    # Leden van de lijst ophalen
    try:
        list_resp = client.app.bsky.graph.get_list({"list": LIST_URI})
        members = list_resp.items
        log(f"📋 {len(members)} accounts in beautygroup-lijst gevonden.")
    except Exception as e:
        log(f"⚠️ Fout bij ophalen lijst: {e}")
        return

    all_posts = []
    total_scanned = 0

    # Voor ieder account de feed ophalen
    for member in members:
        handle = getattr(member.subject, "handle", None)
        did = getattr(member.subject, "did", None)
        actor = handle or did
        if not actor:
            continue

        try:
            feed_resp = client.app.bsky.feed.get_author_feed(
                {"actor": actor, "limit": 30}
            )
        except Exception as e:
            log(f"⚠️ Fout bij ophalen feed van een account: {e}")
            continue

        for item in feed_resp.feed:
            total_scanned += 1

            post = item.post
            record = post.record
            uri = post.uri
            cid = post.cid

            # Reposts overslaan
            if getattr(item, "reason", None) is not None:
                continue

            # Replies overslaan
            if getattr(record, "reply", None):
                continue

            # Als al gedaan, overslaan
            if uri in done:
                continue

            created_dt = parse_time(record, post)
            if not created_dt:
                continue

            if created_dt < cutoff:
                continue

            # Per-user koppelen op basis van auteur DID (stabieler dan handle)
            author_id = getattr(post.author, "did", None) or actor

            all_posts.append(
                {
                    "author_id": author_id,
                    "uri": uri,
                    "cid": cid,
                    "created": created_dt,
                }
            )

    log(f"📊 {len(all_posts)} kandidaten na filtering (van {total_scanned} bekeken).")

    # Oudste eerst
    all_posts.sort(key=lambda x: x["created"])

    reposted = 0
    liked = 0
    per_user_count = {}

    for post in all_posts:
        if reposted >= MAX_PER_RUN:
            break

        author_id = post["author_id"]
        uri = post["uri"]
        cid = post["cid"]

        count = per_user_count.get(author_id, 0)
        if count >= MAX_PER_USER:
            continue

        # Repost
        try:
            client.app.bsky.feed.repost.create(
                repo=client.me.did,
                record={
                    "subject": {"uri": uri, "cid": cid},
                    "createdAt": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "$type": "app.bsky.feed.repost",
                },
            )
            reposted += 1
            per_user_count[author_id] = count + 1
            done.add(uri)

            # Like
            try:
                client.app.bsky.feed.like.create(
                    repo=client.me.did,
                    record={
                        "subject": {"uri": uri, "cid": cid},
                        "createdAt": datetime.now(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        "$type": "app.bsky.feed.like",
                    },
                )
                liked += 1
            except Exception as e_like:
                log(f"⚠️ Fout bij liken van een post: {e_like}")

            # Vertraging tussen posts
            time.sleep(DELAY_SECONDS)

        except Exception as e_rep:
            log(f"⚠️ Fout bij repost: {e_rep}")

    # Repost-log opslaan
    with open(REPOST_LOG_FILE, "w", encoding="utf-8") as f:
        for uri in done:
            f.write(uri + "\n")

    log(f"🔥 Klaar — {reposted} reposts uitgevoerd ({liked} geliked).")
    log(
        f"ℹ️ Per-user limieten toegepast, tijdvenster: laatste {HOURS_BACK} uur, max {MAX_PER_RUN} per run."
    )
    log(f"⏰ Run afgerond op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

if __name__ == "__main__":
    main()
