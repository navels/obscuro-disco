#!/usr/bin/env python3
"""Scrape Obscuro Disco podcast episodes from discoitalo.com."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree


DEFAULT_FEED_URL = "https://www.discoitalo.com/feed/podcast/"
NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "wp": "com-wordpress:feed-additions:1",
}


def text_of(element: ElementTree.Element, selector: str, default: str = "") -> str:
    found = element.find(selector, NS)
    if found is None or found.text is None:
        return default
    return clean_text(found.text)


def raw_text_of(element: ElementTree.Element, selector: str, default: str = "") -> str:
    found = element.find(selector, NS)
    if found is None or found.text is None:
        return default
    return html.unescape(found.text)


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def add_query_param(url: str, key: str, value: int) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = str(value)
    return urlunparse(parsed._replace(query=urlencode(query)))


def fetch_text(url: str, timeout: int = 30) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; obscuro-disco-scraper/1.0; "
                "+https://www.discoitalo.com/)"
            )
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8")


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_cell = False
        self._current_table: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
            self._current_table = []
        elif self._in_table and tag == "tr":
            self._current_row = []
        elif self._in_table and tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._current_row.append(clean_text("".join(self._current_cell)))
            self._current_cell = []
            self._in_cell = False
        elif tag == "tr" and self._in_table:
            if any(self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = []
        elif tag == "table" and self._in_table:
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = []
            self._in_table = False


def normalize_header(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return "number" if value == "" or value == "_" else value


def parse_tracks(content_html: str) -> list[dict[str, str]]:
    parser = TableParser()
    parser.feed(content_html)
    tracks: list[dict[str, str]] = []

    for table in parser.tables:
        if len(table) < 2:
            continue

        headers = [normalize_header(cell) for cell in table[0]]
        if "title" not in headers or "artist" not in headers:
            continue

        for row in table[1:]:
            if not any(row):
                continue
            padded = row + [""] * max(0, len(headers) - len(row))
            track = {headers[index]: padded[index] for index in range(len(headers))}
            tracks.append(track)

    return tracks


def parse_feed_page(xml_text: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []

    episodes: list[dict[str, Any]] = []
    for item in channel.findall("item"):
        content_html = raw_text_of(item, "content:encoded")
        enclosure = item.find("enclosure")
        image = item.find("itunes:image", NS)

        episode_text = text_of(item, "itunes:episode")
        post_id = text_of(item, "wp:post-id")
        categories = [clean_text(category.text or "") for category in item.findall("category")]

        episode: dict[str, Any] = {
            "post_id": int(post_id) if post_id.isdigit() else None,
            "episode": int(episode_text) if episode_text.isdigit() else None,
            "title": text_of(item, "itunes:title") or text_of(item, "title"),
            "rss_title": text_of(item, "title"),
            "link": text_of(item, "link").split("?")[0],
            "guid": text_of(item, "guid"),
            "published": text_of(item, "pubDate"),
            "author": text_of(item, "itunes:author"),
            "subtitle": text_of(item, "itunes:subtitle"),
            "summary": text_of(item, "itunes:summary") or text_of(item, "description"),
            "duration": text_of(item, "itunes:duration"),
            "audio_url": enclosure.attrib.get("url", "") if enclosure is not None else "",
            "audio_length": int(enclosure.attrib["length"])
            if enclosure is not None and enclosure.attrib.get("length", "").isdigit()
            else None,
            "audio_type": enclosure.attrib.get("type", "") if enclosure is not None else "",
            "image_url": image.attrib.get("href", "") if image is not None else "",
            "categories": categories,
            "tracks": parse_tracks(content_html),
        }
        episodes.append(episode)

    return episodes


def scrape_feed(feed_url: str, delay: float = 0.25) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in range(1, 100):
        url = feed_url if page == 1 else add_query_param(feed_url, "paged", page)
        xml_text = fetch_text(url)
        page_episodes = parse_feed_page(xml_text)
        new_episodes = []

        for episode in page_episodes:
            key = str(episode.get("post_id") or episode.get("guid") or episode.get("link"))
            if key not in seen:
                seen.add(key)
                new_episodes.append(episode)

        if not new_episodes:
            break

        episodes.extend(new_episodes)
        print(f"Fetched page {page}: {len(new_episodes)} episodes", file=sys.stderr)
        time.sleep(delay)

        if len(page_episodes) < 10:
            break

    return episodes


def write_json(path: Path, episodes: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(episodes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_tracks_csv(path: Path, episodes: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "episode",
        "episode_title",
        "published",
        "track_number",
        "track_title",
        "artist",
        "time",
        "year",
        "country",
        "episode_link",
        "audio_url",
    ]

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for episode in episodes:
            for track in episode["tracks"]:
                writer.writerow(
                    {
                        "episode": episode["episode"],
                        "episode_title": episode["title"],
                        "published": episode["published"],
                        "track_number": track.get("#") or track.get("number", ""),
                        "track_title": track.get("title", ""),
                        "artist": track.get("artist", ""),
                        "time": track.get("time", ""),
                        "year": track.get("year", ""),
                        "country": track.get("country", ""),
                        "episode_link": episode["link"],
                        "audio_url": episode["audio_url"],
                    }
                )


def download_audio(episodes: list[dict[str, Any]], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for episode in episodes:
        audio_url = episode.get("audio_url", "")
        if not audio_url:
            continue

        filename = Path(urlparse(audio_url).path).name
        if episode.get("episode"):
            filename = f"{int(episode['episode']):02d}-{filename}"
        destination = directory / filename
        if destination.exists() and destination.stat().st_size > 0:
            print(f"Skipping existing {destination}", file=sys.stderr)
            continue

        print(f"Downloading {audio_url}", file=sys.stderr)
        request = Request(audio_url, headers={"User-Agent": "obscuro-disco-scraper/1.0"})
        with urlopen(request, timeout=60) as response, destination.open("wb") as file:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                file.write(chunk)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--json", type=Path, default=Path("data/episodes.json"))
    parser.add_argument("--tracks-csv", type=Path, default=Path("data/tracks.csv"))
    parser.add_argument("--download-audio", action="store_true")
    parser.add_argument("--audio-dir", type=Path, default=Path("data/audio"))
    parser.add_argument("--delay", type=float, default=0.25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        episodes = scrape_feed(args.feed_url, delay=args.delay)
    except (ElementTree.ParseError, HTTPError, URLError, TimeoutError) as error:
        print(f"Scrape failed: {error}", file=sys.stderr)
        return 1

    write_json(args.json, episodes)
    write_tracks_csv(args.tracks_csv, episodes)

    if args.download_audio:
        download_audio(episodes, args.audio_dir)

    track_count = sum(len(episode["tracks"]) for episode in episodes)
    print(f"Wrote {len(episodes)} episodes and {track_count} tracks")
    print(f"JSON: {args.json}")
    print(f"CSV: {args.tracks_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
