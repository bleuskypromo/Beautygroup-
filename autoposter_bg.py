from atproto import Client
import os
import time
from datetime import datetime, timedelta, timezone

# === CONFIG ===
FEED_URI = "at://did:plc:jaka644beit3x4vmmg6yysw7/app.bsky.feed.generator/aaamyqwuiyasw"
MAX_PER_RUN = 100            # Verander indien gewenst
MAX_PER_USER = 3             # Verander indien gewenst
HOURS_BACK = 2               # Laatste 2 uur
DELAY_SECONDS = 2            # 2 seconden vertraging tussen reposts

def log(msg: str):
    """Minimalistische logging zoals NSFW-template"""
    now = datetime.now(timezone.utc).strftime("[%H:%M:%S]")
    print(f"{now} {msg}")

def parse_time(record, post):
    """ timestamp ophalen """
    for attr in ["createdAt", "indexedAt"]:
        val = getattr(record, attr, None) or getattr(post, attr, None)
        if val:
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except:
                continue
    return None

def main():
    client = Client()
    client.login(os.environ["BSKY_USERNAME_BG"], os.environ["BSKY_PASSWORD_BG"])
    log("✅ Ingelogd.")

    try:
        log("📥 Feed ophalen...")
        feed = client.app.bsky.feed.get_feed({"feed": FEED_URI, "limit": 100}).feed
        log(f"📊 {len(feed)} posts gevonden in feed.")
    except Exception as e:
        log(f"⚠️ Feed loading error: {e}")
        return

    repost_log_path = "reposted_bg.txt"
    done = set()
    if os.path.exists(repost_log_path):
        with open(repost_log_path, "r") as f:
            done = set(f.read().splitlines())

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    candidates = []
    per_user_count = {}

    for item in feed:
        post = item.post
        record = post.record
        uri = post.uri
        cid = post.cid
        handle = post.author.handle

        created_dt = parse_time(record, post)
        if not created_dt or created_dt < cutoff:
            continue
        if uri in done:
            continue

        per_user_count[handle] = per_user_count.get(handle, 0)
        if per_user_count[handle] >= MAX_PER_USER:
            continue

        candidates.append({"uri": uri, "cid": cid, "handle": handle, "created": created_dt})

    # Oudste eerst
    candidates.sort(key=lambda x: x["created"])
    candidates = candidates[:MAX_PER_RUN]

    total = len(candidates)
    log(f"🧩 {total} geschikte posts gevonden.")

    reposted = 0
    liked = 0

    for idx, post in enumerate(candidates, start=1):
        try:
            client.app.bsky.feed.repost.create(
                repo=client.me.did,
                record={
                    "subject": {"uri": post["uri"], "cid": post["cid"]},
                    "createdAt": client.get_current_time_iso(),
                    "$type": "app.bsky.feed.repost",
                },
            )
            reposted += 1
            done.add(post["uri"])
            per_user_count[post["handle"]] += 1

            try:
                client.app.bsky.feed.like.create(
                    repo=client.me.did,
                    record={
                        "subject": {"uri": post["uri"], "cid": post["cid"]},
                        "createdAt": client.get_current_time_iso(),
                        "$type": "app.bsky.feed.like",
                    },
                )
                liked += 1
            except:
                pass

            if idx < total:
                time.sleep(DELAY_SECONDS)

        except Exception as e:
            log(f"⚠️ {e}")

    with open(repost_log_path, "w") as f:
        f.write("\n".join(done))

    log(f"🔥 Klaar — {reposted} reposts uitgevoerd ({liked} geliked).")
    log(f"⏰ Run afgerond op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

if __name__ == "__main__":
    main()