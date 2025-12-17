from atproto import Client
import os
import time
from datetime import datetime, timezone
from typing import Optional

# === CONFIG: LIST ===
# Link: https://bsky.app/profile/did:plc:u56y5ibuou5wzgg6frc5eiyr/lists/3lwyvdqvkob2e
LIST_URI = "at://did:plc:u56y5ibuou5wzgg6frc5eiyr/app.bsky.graph.list/3lwyvdqvkob2e"

LIST_FEED_LIMIT = 100        # max 100 per request (API limiet)
MAX_USERS_PER_RUN = 50       # max unieke authors per run
SLEEP_SECONDS = 1


def log(msg: str) -> None:
    now = datetime.now(timezone.utc).strftime("[%H:%M:%S]")
    print(f"{now} {msg}")


def _rkey_from_record_uri(uri: str) -> Optional[str]:
    # verwacht: at://did/.../collection/rkey
    if not uri or "/" not in uri:
        return None
    return uri.rsplit("/", 1)[-1]


def delete_repost_if_exists(client: Client, post_view) -> None:
    viewer = getattr(post_view, "viewer", None)
    repost_record_uri = getattr(viewer, "repost", None) if viewer else None
    if not repost_record_uri:
        return

    rkey = _rkey_from_record_uri(repost_record_uri)
    if not rkey:
        log(f"⚠️ Kon rkey niet parsen uit repost-uri: {repost_record_uri}")
        return

    try:
        client.app.bsky.feed.repost.delete(repo=client.me.did, rkey=rkey)
        log("🧹 Oude repost verwijderd.")
    except Exception as e:
        log(f"⚠️ Kon oude repost niet verwijderen ({repost_record_uri}): {e}")


def delete_like_if_exists(client: Client, post_view) -> None:
    viewer = getattr(post_view, "viewer", None)
    like_record_uri = getattr(viewer, "like", None) if viewer else None
    if not like_record_uri:
        return

    rkey = _rkey_from_record_uri(like_record_uri)
    if not rkey:
        log(f"⚠️ Kon rkey niet parsen uit like-uri: {like_record_uri}")
        return

    try:
        client.app.bsky.feed.like.delete(repo=client.me.did, rkey=rkey)
        log("🧹 Oude like verwijderd.")
    except Exception as e:
        log(f"⚠️ Kon oude like niet verwijderen ({like_record_uri}): {e}")


def is_quote_post(record) -> bool:
    embed = getattr(record, "embed", None)
    if not embed:
        return False
    return bool(getattr(embed, "record", None) or getattr(embed, "recordWithMedia", None))


def has_media(record) -> bool:
    """Alleen echte media: images/video (geen link-cards)."""
    embed = getattr(record, "embed", None)
    if not embed:
        return False

    images = getattr(embed, "images", None)
    if isinstance(images, list) and images:
        return True

    # video direct
    if getattr(embed, "video", None):
        return True

    # recordWithMedia / media container
    media = getattr(embed, "media", None)
    if media:
        imgs = getattr(media, "images", None)
        if isinstance(imgs, list) and imgs:
            return True
        if getattr(media, "video", None):
            return True

    return False


def main():
    # Gebruik bestaande BeautyGroup secrets
    username = os.environ.get("BSKY_USERNAME_BG")
    password = os.environ.get("BSKY_PASSWORD_BG")

    if not username or not password:
        log("❌ Geen inloggegevens (BSKY_USERNAME_BG / BSKY_PASSWORD_BG). Stop.")
        return

    client = Client()
    client.login(username, password)
    log("✅ Ingelogd als BeautyGroup.")

    # List feed ophalen (max limit=100)
    try:
        log("📥 List feed ophalen...")
        resp = client.app.bsky.feed.get_list_feed({"list": LIST_URI, "limit": LIST_FEED_LIMIT})
        items = resp.feed or []
        log(f"📊 {len(items)} items gevonden in list feed.")
    except Exception as e:
        log(f"⚠️ Fout bij ophalen list feed: {e}")
        return

    # Per author de nieuwste media post (newest-first => eerste per handle = nieuwste)
    newest_per_user: dict[str, dict] = {}

    for item in items:
        post_view = item.post
        record = post_view.record

        # ❌ skip reposts/boosts
        if getattr(item, "reason", None) is not None:
            continue

        # ❌ skip replies
        if getattr(record, "reply", None):
            continue

        # ❌ skip quotes
        if is_quote_post(record):
            continue

        # ✅ alleen foto/video (geen text-only)
        if not has_media(record):
            continue

        handle = getattr(post_view.author, "handle", "unknown")

        # per handle slechts 1 (de nieuwste)
        if handle in newest_per_user:
            continue

        newest_per_user[handle] = {
            "handle": handle,
            "uri": post_view.uri,
            "cid": post_view.cid,
            "post_view": post_view,  # nodig voor viewer.like/repost delete
        }

        if len(newest_per_user) >= MAX_USERS_PER_RUN:
            break

    selected = list(newest_per_user.values())
    log(f"🧩 {len(selected)} accounts: nieuwste foto/video geselecteerd.")

    if not selected:
        log("🔥 Klaar — niets te doen.")
        return

    reposted = 0
    liked = 0

    for p in selected:
        handle = p["handle"]
        uri = p["uri"]
        cid = p["cid"]
        post_view = p["post_view"]

        # ✅ altijd eerst schoonmaken (unrepost/unlike)
        delete_repost_if_exists(client, post_view)
        delete_like_if_exists(client, post_view)

        # ✅ repost
        try:
            client.app.bsky.feed.repost.create(
                repo=client.me.did,
                record={
                    "subject": {"uri": uri, "cid": cid},
                    "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
            reposted += 1
            log(f"🔁 Gerepost (nieuwste media) van @{handle}")
        except Exception as e:
            log(f"⚠️ Repost fout @{handle}: {e}")
            continue

        # ✅ like
        try:
            client.app.bsky.feed.like.create(
                repo=client.me.did,
                record={
                    "subject": {"uri": uri, "cid": cid},
                    "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
            liked += 1
        except Exception as e:
            log(f"⚠️ Like fout @{handle}: {e}")

        time.sleep(SLEEP_SECONDS)

    log(f"✅ Klaar — {reposted} reposts ({liked} likes).")


if __name__ == "__main__":
    main()
```0