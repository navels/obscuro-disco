#!/usr/bin/env python3
"""Generate a static podcast RSS feed for Obscuro Disco."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, indent, tostring


DEFAULT_EPISODES = Path("data/episodes.json")
DEFAULT_TITLE = "Obscuro Disco"
DEFAULT_SITE = "https://www.discoitalo.com/shows/"
DEFAULT_FEED_URL = "https://navels.github.io/obscuro-disco/obscuro-disco.xml"
DEFAULT_DESCRIPTION = "Exploring 80s European Disco"
DEFAULT_AUTHOR = "DiscoItalo.com"
DEFAULT_OWNER_NAME = "DiscoItalo.com"
DEFAULT_OWNER_EMAIL = "david@dthunter.com"
DEFAULT_IMAGE_URL = "https://www.discoitalo.com/wp-content/uploads/2021/02/ObscuroDisco-podcast.jpg"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_rfc2822(value: str) -> datetime:
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def playlist_text(tracks: list[dict[str, str]]) -> str:
    lines = []
    for track in tracks:
        number = track.get("number", "")
        title = track.get("title", "")
        artist = track.get("artist", "")
        year = track.get("year", "")
        country = track.get("country", "")
        time = track.get("time", "")
        detail = " / ".join(part for part in [year, country, time] if part)
        prefix = f"{number}. " if number else ""
        suffix = f" ({detail})" if detail else ""
        lines.append(f"{prefix}{title} - {artist}{suffix}".strip())
    return "\n".join(lines)


def item_description(episode: dict[str, Any]) -> str:
    parts = []
    if episode.get("summary"):
        parts.append(clean_text(str(episode["summary"])))
    if episode.get("tracks"):
        parts.append("Playlist:\n" + playlist_text(episode["tracks"]))
    return "\n\n".join(parts)


def build_rss(
    episodes: list[dict[str, Any]],
    title: str,
    site: str,
    feed_url: str,
    description: str,
    author: str,
    owner_name: str,
    owner_email: str,
    image_url: str,
) -> str:
    episodes = sorted(
        episodes,
        key=lambda episode: parse_rfc2822(episode["published"]),
        reverse=True,
    )
    latest = parse_rfc2822(episodes[0]["published"]) if episodes else datetime.now(timezone.utc)

    rss = Element(
        "rss",
        {
            "version": "2.0",
            "xmlns:atom": "http://www.w3.org/2005/Atom",
            "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
            "xmlns:content": "http://purl.org/rss/1.0/modules/content/",
        },
    )
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = title
    atom_link = SubElement(channel, "atom:link")
    atom_link.set("href", feed_url)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")
    SubElement(channel, "link").text = site
    SubElement(channel, "description").text = description
    SubElement(channel, "lastBuildDate").text = format_datetime(latest)
    SubElement(channel, "language").text = "en-US"
    SubElement(channel, "generator").text = "generate_podcast_rss.py"
    SubElement(channel, "itunes:summary").text = description
    SubElement(channel, "itunes:author").text = author
    SubElement(channel, "itunes:explicit").text = "clean"
    SubElement(channel, "itunes:type").text = "episodic"
    owner = SubElement(channel, "itunes:owner")
    SubElement(owner, "itunes:name").text = owner_name
    SubElement(owner, "itunes:email").text = owner_email
    itunes_image = SubElement(channel, "itunes:image")
    itunes_image.set("href", image_url)
    image = SubElement(channel, "image")
    SubElement(image, "title").text = title
    SubElement(image, "url").text = image_url
    SubElement(image, "link").text = site
    category = SubElement(channel, "itunes:category")
    category.set("text", "Music")
    subcategory = SubElement(category, "itunes:category")
    subcategory.set("text", "Music History")

    for episode in episodes:
        item = SubElement(channel, "item")
        pubdate = parse_rfc2822(episode["published"])
        audio_url = episode["audio_url"]

        SubElement(item, "title").text = episode["title"]
        SubElement(item, "link").text = episode["link"]
        guid = SubElement(item, "guid")
        guid.set("isPermaLink", "false")
        guid.text = episode.get("guid") or episode["link"]
        SubElement(item, "description").text = item_description(episode)
        SubElement(item, "pubDate").text = format_datetime(pubdate)
        enclosure = SubElement(item, "enclosure")
        enclosure.set("url", audio_url)
        enclosure.set("type", episode.get("audio_type") or "audio/mpeg")
        if episode.get("audio_length"):
            enclosure.set("length", str(episode["audio_length"]))
        if episode.get("episode") is not None:
            SubElement(item, "itunes:episode").text = str(episode["episode"])
        SubElement(item, "itunes:episodeType").text = "full"
        if episode.get("duration"):
            SubElement(item, "itunes:duration").text = episode["duration"]
        if episode.get("subtitle"):
            SubElement(item, "itunes:subtitle").text = clean_text(episode["subtitle"])
        if episode.get("summary"):
            SubElement(item, "itunes:summary").text = clean_text(episode["summary"])
        if episode.get("author"):
            SubElement(item, "itunes:author").text = episode["author"]
        if episode.get("image_url"):
            episode_image = SubElement(item, "itunes:image")
            episode_image.set("href", episode["image_url"])

    indent(rss, space="  ")
    return tostring(rss, encoding="utf-8", xml_declaration=True).decode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=Path, default=DEFAULT_EPISODES)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--site", default=DEFAULT_SITE)
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--author", default=DEFAULT_AUTHOR)
    parser.add_argument("--owner-name", default=DEFAULT_OWNER_NAME)
    parser.add_argument("--owner-email", default=DEFAULT_OWNER_EMAIL)
    parser.add_argument("--image-url", default=DEFAULT_IMAGE_URL)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    episodes = json.loads(args.episodes.read_text(encoding="utf-8"))
    if not isinstance(episodes, list):
        print(f"Expected a list in {args.episodes}", file=sys.stderr)
        return 1

    sys.stdout.write(
        build_rss(
            episodes=episodes,
            title=args.title,
            site=args.site,
            feed_url=args.feed_url,
            description=args.description,
            author=args.author,
            owner_name=args.owner_name,
            owner_email=args.owner_email,
            image_url=args.image_url,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
