from atproto import Client
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# === CONFIG ===
# BeautyGroup-feed (NIET de lijst, maar de feed-URL)
FEED_URI = "at://did:plc:jaka644beit3x4vmmg6yysw7/app.bsky.feed.generator/aaamyqwuiyasw"

MAX_PER_RUN = 100          # max reposts per run
MAX_PER_USER = 3           # max reposts per account per run
HOURS_BACK = 12            # tijdvenster: laatste 3 uur
SLEEP_SECONDS = 2          # vertraging tussen reposts/likes
REPOST_LOG = "reposted_bg.txt"  # eigen logbestand voor BeautyGroup


def log(msg: str) -> None:
    """Eenvoudige logger met tijdstempel."""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")


def load_repost_log(path: str) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    with p.open("r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def append_to_repost_log(path: str, uri: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(uri + "\n")


def get_created_dt(record, post):
    """Zoekt naar een bruikbare timestamp op record of post."""
    for attr in ("createdAt", "indexedAt", "created_at", "timestamp"):
        val = getattr(record, attr, None) or getattr(post, attr, None)
        if not val:
            continue
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            continue
    return None


def main():
    username = os.environ.get("BSKY_USERNAME_BG")
    password = os.environ.get("BSKY_PASSWORD_BG")

    if not username or not password:
        log("❌ Geen inloggegevens (BSKY_USERNAME_BG / BSKY_PASSWORD_BG). Stop.")
        return

    client = Client()
    client.login(username, password)
    log("✅ Ingelogd.")

    # Repost-log laden (alleen voor BeautyGroup)
    already_reposted = load_repost_log(REPOST_LOG)

    # Feed ophalen
    try:
        log("📥 Feed ophalen...")
        feed = client.app.bsky.feed.get_feed({"feed": FEED_URI, "limit": 100})
        items = feed.feed
        log(f"📊 {len(items)} posts gevonden in feed.")
    except Exception as e:
        log(f"⚠️ Fout bij ophalen feed: {e}")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)

    candidates: list[dict] = []

    # Oudste eerst verwerken
    for item in reversed(items):
        post = item.post
        record = post.record
        uri = post.uri

        # skip reposts/quotes/reasons
        if getattr(item, "reason", None) is not None:
            continue

        # skip replies
        if getattr(record, "reply", None):
            continue

        # al gedaan in vorige run?
        if uri in already_reposted:
            continue

        created_dt = get_created_dt(record, post)
        if not created_dt or created_dt < cutoff:
            continue

        handle = getattr(post.author, "handle", "unknown")
        candidates.append(
            {
                "uri": uri,
                "cid": post.cid,
                "handle": handle,
                "created": created_dt,
            }
        )

    log(f"🧩 {len(candidates)} geschikte posts gevonden.")

    if not candidates:
        log("🔥 Klaar — 0 reposts uitgevoerd (0 geliked).")
        log(f"⏰ Run afgerond op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        return

    # Oudste eerst
    candidates.sort(key=lambda x: x["created"])

    per_user_count: dict[str, int] = {}
    reposted_count = 0
    liked_count = 0

    for post_data in candidates:
        if reposted_count >= MAX_PER_RUN:
            break

        uri = post_data["uri"]
        cid = post_data["cid"]
        handle = post_data["handle"]

        per_user_count.setdefault(handle, 0)
        if per_user_count[handle] >= MAX_PER_USER:
            continue

        try:
            # Repost
            client.app.bsky.feed.repost.create(
                repo=client.me.did,
                record={
                    "subject": {"uri": uri, "cid": cid},
                    "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
            reposted_count += 1
            per_user_count[handle] += 1
            already_reposted.add(uri)
            append_to_repost_log(REPOST_LOG, uri)

            # Like
            try:
                client.app.bsky.feed.like.create(
                    repo=client.me.did,
                    record={
                        "subject": {"uri": uri, "cid": cid},
                        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                )
                liked_count += 1
            except Exception as e_like:
                log(f"⚠️ Fout bij liken: {e_like}")

            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            log(f"⚠️ Fout bij repost: {e}")

    log(f"🔥 Klaar — {reposted_count} reposts uitgevoerd ({liked_count} geliked).")
    log(
        f"ℹ️ Per-user limieten toegepast, tijdvenster: laatste {HOURS_BACK} uur, "
        f"max {MAX_PER_RUN} per run, max {MAX_PER_USER} per account."
    )
    log(f"⏰ Run afgerond op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")


if __name__ == "__main__":
    main()