#!/usr/bin/env python3
"""otto-social-mcp — thin multi-tenant MCP server for Meta organic publishing.

One instance per client agent (stdio). Tenant identity comes entirely from env:
  META_ACCESS_TOKEN   long-lived Page/user token with pages_manage_posts,
                      instagram_basic, instagram_content_publish
  META_PAGE_ID        Facebook Page id
  META_IG_USER_ID     Instagram Business account id (optional; IG tools error without it)
  GRAPH_API_VERSION   optional, default v26.0 (the engine's otto_publish.GRAPH_VERSION)

Tools: fb_page_post, ig_publish_image, ig_publish_carousel, ig_publish_reel,
ig_publish_story, ig_publishing_limit, page_insights.

IG publishing uses the two-step container -> publish flow. Reels/stories poll the
container status until FINISHED (video processing is async on Meta's side).
"""

import os
import time

import requests
from mcp.server.mcpserver import MCPServer

GRAPH = "https://graph.facebook.com/" + (os.environ.get("GRAPH_API_VERSION") or "v26.0")
TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
PAGE_ID = os.environ.get("META_PAGE_ID", "")
IG_USER_ID = os.environ.get("META_IG_USER_ID", "")

mcp = MCPServer("otto-social")


class GraphError(Exception):
    pass


def _call(method: str, path: str, **params) -> dict:
    if not TOKEN:
        raise GraphError("META_ACCESS_TOKEN is not set for this client")
    params["access_token"] = TOKEN
    resp = requests.request(method, f"{GRAPH}/{path}", params=params, timeout=60)
    data = resp.json()
    if "error" in data:
        err = data["error"]
        raise GraphError(f"Graph API error {err.get('code')}: {err.get('message')}")
    return data


def _require_ig() -> None:
    if not IG_USER_ID:
        raise GraphError("META_IG_USER_ID is not set — connect an Instagram Business account first")


def _wait_for_container(creation_id: str, timeout_s: int = 300) -> None:
    """Poll an IG media container until Meta finishes processing it."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _call("GET", creation_id, fields="status_code")["status_code"]
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise GraphError(f"container {creation_id} failed processing")
        time.sleep(5)
    raise GraphError(f"container {creation_id} not ready after {timeout_s}s")


def _ig_publish(creation_id: str) -> dict:
    return _call("POST", f"{IG_USER_ID}/media_publish", creation_id=creation_id)


@mcp.tool()
def fb_page_post(message: str, link: str = "", image_url: str = "",
                 scheduled_unix_time: int = 0) -> dict:
    """Publish (or schedule) a post on the connected Facebook Page.

    Provide image_url for a photo post, link for a link post, neither for text.
    scheduled_unix_time > 0 schedules instead of publishing now (10 min - 30 days ahead).
    Returns the created post/photo id.
    """
    params: dict = {}
    if scheduled_unix_time:
        params.update(published="false", scheduled_publish_time=scheduled_unix_time)
    if image_url:
        params.update(url=image_url, caption=message)
        return _call("POST", f"{PAGE_ID}/photos", **params)
    params["message"] = message
    if link:
        params["link"] = link
    return _call("POST", f"{PAGE_ID}/feed", **params)


@mcp.tool()
def ig_publish_image(caption: str, image_url: str) -> dict:
    """Publish a single image to the connected Instagram Business account.
    image_url must be a public URL (JPEG). Returns the published media id."""
    _require_ig()
    container = _call("POST", f"{IG_USER_ID}/media", image_url=image_url, caption=caption)
    return _ig_publish(container["id"])


@mcp.tool()
def ig_publish_carousel(caption: str, image_urls: list[str]) -> dict:
    """Publish a 2-10 image carousel to Instagram. Returns the published media id."""
    _require_ig()
    if not 2 <= len(image_urls) <= 10:
        raise GraphError("carousel needs 2-10 images")
    children = [
        _call("POST", f"{IG_USER_ID}/media", image_url=url, is_carousel_item="true")["id"]
        for url in image_urls
    ]
    container = _call("POST", f"{IG_USER_ID}/media", media_type="CAROUSEL",
                      children=",".join(children), caption=caption)
    return _ig_publish(container["id"])


@mcp.tool()
def ig_publish_reel(caption: str, video_url: str, share_to_feed: bool = True) -> dict:
    """Publish a reel to Instagram. video_url must be a public MP4 (MOV/MP4, <=90s
    for feed-shared reels). Waits for Meta's async video processing. Returns media id."""
    _require_ig()
    container = _call("POST", f"{IG_USER_ID}/media", media_type="REELS",
                      video_url=video_url, caption=caption,
                      share_to_feed="true" if share_to_feed else "false")
    _wait_for_container(container["id"])
    return _ig_publish(container["id"])


@mcp.tool()
def ig_publish_story(image_url: str = "", video_url: str = "") -> dict:
    """Publish a story to Instagram from a public image OR video URL. Returns media id."""
    _require_ig()
    if bool(image_url) == bool(video_url):
        raise GraphError("provide exactly one of image_url / video_url")
    params = {"media_type": "STORIES"}
    if image_url:
        params["image_url"] = image_url
    else:
        params["video_url"] = video_url
    container = _call("POST", f"{IG_USER_ID}/media", **params)
    if video_url:
        _wait_for_container(container["id"])
    return _ig_publish(container["id"])


@mcp.tool()
def ig_publishing_limit() -> dict:
    """Check how much of the 24h Instagram publishing quota (100 posts) is used."""
    _require_ig()
    return _call("GET", f"{IG_USER_ID}/content_publishing_limit",
                 fields="quota_usage,config")


@mcp.tool()
def page_insights(metrics: str = "page_media_view,page_total_media_view_unique,page_post_engagements",
                  period: str = "day") -> dict:
    """Fetch Facebook Page insights. metrics is a comma-separated Graph metric list. Meta retired page_impressions* and
    page_fans* (invalid-metric error since 15.11.2025): use page_media_view / page_total_media_view_unique / page_follows."""
    return _call("GET", f"{PAGE_ID}/insights", metric=metrics, period=period)


if __name__ == "__main__":
    mcp.run()
