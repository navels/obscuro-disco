# Obscuro Disco Podcast Feed

Static podcast feed for the archived Obscuro Disco episodes from DiscoItalo.com.

The feed is generated from `data/episodes.json` and keeps each episode's original MP3 URL as the enclosure URL. Audio files are not hosted in this repository.

Generate the feed:

```sh
python3 generate_podcast_rss.py > obscuro-disco.xml
```

Published feed URL after GitHub Pages is enabled:

```text
https://navels.github.io/obscuro-disco/obscuro-disco.xml
```

This podcast appears to be static: 33 episodes published from February 14, 2021 through November 28, 2021. There is no scheduled update workflow.
