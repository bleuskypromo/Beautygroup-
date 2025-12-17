from atproto import Client
import os
import time
from datetime import datetime, timezone
from typing import Optional

# === CONFIG: LIST ===
# Link: https://bsky.app/profile/did:plc:u56y5ibuou5wzgg6frc5eiyr/lists/3lwyvdqvkob2e
LIST_URI = "at://did:plc:u56y5ibuou5wzgg6frc5eiyr/app.bsky.graph.list/3lwyvdqvkob2e"

LIST_FEED_LIMIT = 100        # API max is 100
MAX_USERS_PER_RUN = 50       # max unieke authors per run
SLEEP_SECONDS = 1


def log(msg: str) -> None:
    now = datetime.now(timezone.utc).strftime("[%H:%M:%S]")
    print(f"{now} {msg}")


def rkey_from_record_uri(uri: str) -> Optional[str]:
    # verwacht: at://did/.../collection/rkey
    if not uri or "/" not in uri:
        return None
    return uri.rsplit("/", 1)[-1]


def delete_repost_if_exists(client: Client, post_view) -> None:
    viewer = getattr(post_view, "viewer", None)
    repost_record_uri = getattr(viewer, "repost", None) if viewer else None
    if not repost_record_uri:
        return

    rkey = rkey_from_record_uri(repost_record_uri)
    if not rkey:
        log(f"WARNING: cannot parse rkey from repost uri: {repost_record_uri}")
        return

    try:
        client.app.bsky.feed.repost.delete(repo=client.me.did, rkey=rkey)
        log("Removed old repost.")
    except Exception as e:
        log(f"WARNING: failed to delete repost ({repost_record_uri}): {e}")


def delete_like_if_exists(client: Client, post_view) -> None:
    viewer = getattr(post_view, "viewer", None)
    like_record_uri = getattr(viewer, "like", None) if viewer else None
    if not like_record_uri:
        return

    rkey = rkey_from_record_uri(like_record_uri)
    if not rkey:
        log(f"WARNING: cannot parse rkey from like uri: {like_record_uri}")
        return

    try:
        client.app.bsky.feed.like.delete(repo=client.me.did, rkey=rkey)
        log("Removed old like.")
    except Exception as e:
        log(f"WARNING: failed to delete like ({like_record_uri}): {e}")


def is_quote_post(record) -> bool:
    embed = getattr(record, "embed", None)
    if not embed:
        return False
    return bool(getattr(embed, "record", None) or getattr(embed, "recordWithMedia", None))


def has_media(record) -> bool:
    """
    Alleen echte media: images/video (geen link-cards).
    """
    embed = getattr(record, "embed", None)
    if not embed:
        return False

    images = getattr(embed, "images", None)
    if isinstance(images, list) and images:
        return True

    if getattr(embed, "video", None):
        return True

    media = getattr(embed, "media", None)
    if media:
        imgs = getattr(media, "images", None)
        if isinstance(imgs, list) and imgs:
            return True
        if getattr(media, "video", None):
            return True

    return False


def main() -> None:
    username = os.environ.get("BSKY_USERNAME_BG")
    password = os.environ.get("BSKY_PASSWORD_BG")

    if not username or not password:
        log("ERROR: Missing BSKY_USERNAME_BG / BSKY_PASSWORD_BG")
        return

    client = Client()
    client.login(username, password)
    log("Logged in as BeautyGroup.")

    try:
        log("Fetching list feed...")
        resp = client.app.bsky.feed.get_list_feed({"list": LIST_URI, "limit": LIST_FEED_LIMIT})
        items = resp.feed or []
        log(f"Found {len(items)} items in list feed.")
    except Exception as e:
        log(f"ERROR: failed to fetch list feed: {e}")
        return

    newest_per_user: dict[str, dict] = {}

    for item in items:
        post_view = item.post
        record = post_view.record

        # skip reposts/boosts
        if getattr(item, "reason", None) is not None:
            continue

        # skip replies
        if getattr(record, "reply", None):
            continue

        # skip quotes
        if is_quote_post(record):
            continue

        # only photo/video (no text-only)
        if not has_media(record):
            continue

        handle = getattr(post_view.author, "handle", "unknown")

        if handle in newest_per_user:
            continue

        newest_per_user[handle] = {
            "handle": handle,
            "uri": post_view.uri,
            "cid": post_view.cid,
            "post_view": post_view,
        }

        if len(newest_per_user) >= MAX_USERS_PER_RUN:
            break

    selected = list(newest_per_user.values())
    log(f"Selected {len(selected)} accounts (newest photo/video per account).")

    if not selected:
        log("Nothing to do.")
        return

    reposted = 0
    liked = 0

    for p in selected:
        handle = p["handle"]
        uri = p["uri"]
        cid = p["cid"]
        post_view = p["post_view"]

        # always clean old repost/like first
        delete_repost_if_exists(client, post_view)
        delete_like_if_exists(client, post_view)

        # repost
        try:
            client.app.bsky.feed.repost.create(
                repo=client.me.did,
                record={
                    "subject": {"uri": uri, "cid": cid},
                    "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
            reposted += 1
            log(f"Reposted newest media from @{handle}")
        except Exception as e:
            log(f"WARNING: repost failed for @{handle}: {e}")
            continue

        # like
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
            log(f"WARNING: like failed for @{handle}: {e}")

        time.sleep(SLEEP_SECONDS)

    log(f"Done. reposts={reposted}, likes={liked}")


if __name__ == "__main__":
    main()