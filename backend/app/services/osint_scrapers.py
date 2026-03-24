"""
OSINT Scrapers for Geopolitical Intelligence.

Automated data feed adapters for:
- GDELT: Global event database (conflict events, diplomatic meetings)
- News APIs: EventRegistry, NewsAPI for article aggregation
- YouTube: Monitor news channels for breaking updates (titles, descriptions, transcripts)
- News websites: RSS feeds from major outlets
- Economic data: Oil prices, World Bank indicators
- Military databases: SIPRI arms transfers (manual import)

Each adapter outputs data compatible with DataIngestor.
"""

import json
import logging
import hashlib
import html
import os
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger('mirofish.osint_scrapers')


@dataclass
class OSINTFeed:
    """Configuration for an OSINT data feed."""
    feed_id: str
    feed_name: str
    feed_type: str  # gdelt, newsapi, oil_price, world_bank, sipri
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    poll_interval_minutes: int = 60
    enabled: bool = True
    last_fetched: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)


class GDELTScraper:
    """Scrapes GDELT (Global Database of Events, Language, and Tone).

    GDELT tracks events worldwide from news media in 100+ languages.
    Uses the GDELT 2.0 API (free, no key required).
    """

    BASE_URL = "https://api.gdeltproject.org/api/v2"

    def __init__(self):
        self.last_fetch_time = None

    def fetch_events(
        self,
        query: str = "Iran OR Israel OR Hezbollah OR Houthi",
        mode: str = "artlist",
        max_records: int = 50,
        timespan: str = "24h",
        source_country: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch events from GDELT matching geopolitical query.

        Args:
            query: Search query (actors, events)
            mode: 'artlist' for articles, 'timeline' for timeline
            max_records: Max results
            timespan: Time window (e.g., '24h', '7d')
            source_country: Filter by source country code
        """
        try:
            import requests

            params = {
                "query": query,
                "mode": mode,
                "maxrecords": max_records,
                "format": "json",
                "timespan": timespan,
            }
            if source_country:
                params["sourcecountry"] = source_country

            resp = requests.get(
                f"{self.BASE_URL}/doc/doc",
                params=params,
                timeout=30,
            )

            if resp.status_code != 200:
                logger.error(f"GDELT fetch failed: {resp.status_code}")
                return []

            data = resp.json()
            articles = data.get("articles", [])

            results = []
            for article in articles:
                results.append({
                    "title": article.get("title", ""),
                    "url": article.get("url", ""),
                    "source": article.get("domain", ""),
                    "source_country": article.get("sourcecountry", ""),
                    "language": article.get("language", ""),
                    "timestamp": article.get("seendate", ""),
                    "tone": article.get("tone", 0),
                    "image_url": article.get("socialimage", ""),
                })

            self.last_fetch_time = datetime.now().isoformat()
            logger.info(f"GDELT: fetched {len(results)} articles for query '{query}'")
            return results

        except ImportError:
            logger.warning("requests not installed — skipping GDELT fetch")
            return []
        except Exception as e:
            logger.error(f"GDELT fetch error: {e}")
            return []


class OilPriceScraper:
    """Fetches real-time oil prices from public APIs."""

    def fetch_prices(self) -> Dict[str, Any]:
        """Fetch current Brent and WTI crude oil prices."""
        try:
            import requests

            # Using a free oil price API
            resp = requests.get(
                "https://api.api-ninjas.com/v1/commodityprice?name=crude_oil",
                timeout=10,
            )

            if resp.status_code == 200:
                data = resp.json()
                return {
                    "timestamp": datetime.now().isoformat(),
                    "source": "api-ninjas",
                    "prices": data,
                }

            # Fallback: try alternative source
            return {
                "timestamp": datetime.now().isoformat(),
                "source": "unavailable",
                "note": "Oil price API returned non-200 status. Manual input recommended.",
            }

        except Exception as e:
            logger.warning(f"Oil price fetch failed: {e}")
            return {
                "timestamp": datetime.now().isoformat(),
                "source": "error",
                "error": str(e),
            }


class NewsAPIScraper:
    """Fetches news articles from NewsAPI.org or EventRegistry."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def fetch_articles(
        self,
        query: str = "Iran war",
        sources: Optional[str] = None,
        language: str = "en",
        page_size: int = 20,
        from_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch news articles matching query.

        Args:
            query: Search query
            sources: Comma-separated source IDs (e.g., 'al-jazeera-english,reuters,associated-press')
            language: Language code
            page_size: Number of results
            from_date: ISO date to search from
        """
        if not self.api_key:
            logger.warning("NewsAPI key not configured")
            return []

        try:
            import requests

            params = {
                "q": query,
                "language": language,
                "pageSize": page_size,
                "apiKey": self.api_key,
                "sortBy": "publishedAt",
            }
            if sources:
                params["sources"] = sources
            if from_date:
                params["from"] = from_date

            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params=params,
                timeout=15,
            )

            if resp.status_code != 200:
                logger.error(f"NewsAPI failed: {resp.status_code}")
                return []

            data = resp.json()
            articles = data.get("articles", [])

            results = []
            for article in articles:
                results.append({
                    "title": article.get("title", ""),
                    "content": article.get("content", article.get("description", "")),
                    "source": article.get("source", {}).get("name", ""),
                    "author": article.get("author", ""),
                    "url": article.get("url", ""),
                    "timestamp": article.get("publishedAt", ""),
                    "image_url": article.get("urlToImage", ""),
                })

            logger.info(f"NewsAPI: fetched {len(results)} articles for '{query}'")
            return results

        except ImportError:
            logger.warning("requests not installed")
            return []
        except Exception as e:
            logger.error(f"NewsAPI error: {e}")
            return []


class YouTubeScraper:
    """Monitors YouTube news channels for breaking geopolitical updates.

    Uses YouTube Data API v3 (free tier: 10,000 units/day) to pull recent
    videos, and youtube-transcript-api to get transcripts when available.
    No API key needed for transcript extraction.
    """

    # Pre-configured channels for Iran conflict monitoring
    # Format: (channel_id, channel_name, credibility, bias_note)
    DEFAULT_CHANNELS = [
        # Independent / Less biased
        ("UCMy4o6_qFR0tMr-5FYCr8Gw", "Breaking Points", "news_tier1", "independent, less establishment bias"),
        ("UCNye-wNBqNL5ZzHSJj3l8Bg", "Al Jazeera English", "news_tier1", "less biased for Middle East per user preference"),
        # International
        ("UC16niRr50-MSBwiO3YDb3RA", "BBC News", "news_tier2", "UK perspective"),
        ("UCupvZG-5ko_eiXAupbDfxWw", "CNN", "news_tier2", "US establishment perspective"),
        ("UCeY0bbntWzzVIaj2z3QigXg", "NBC News", "news_tier2", "US mainstream"),
        # Specialist / Analysis
        ("UCwnKziETDbHJtx78nIkfYug", "Sky News", "news_tier2", "UK perspective"),
        ("UCIALMKvObZNtJ68-rmLjvSA", "TLDR News Global", "news_tier1", "analysis-focused, neutral"),
        ("UCBi2mrWuNuyYy4gbM6fU18Q", "CNBC", "news_tier2", "economic/markets focus"),
        # Regional
        ("UCHqC-yWZ1kri4YzwRSt6IGA", "TRT World", "news_tier2", "Turkish perspective"),
        ("UCQ2sg7vS7JkV_15HD-UNRMw", "India Today", "news_tier2", "Indian perspective"),
    ]

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.channels = list(self.DEFAULT_CHANNELS)
        self.last_fetch_time = None
        self._seen_video_ids: set = set()

    def add_channel(self, channel_id: str, name: str,
                    credibility: str = "news_tier2", bias_note: str = ""):
        """Add a YouTube channel to monitor."""
        self.channels.append((channel_id, name, credibility, bias_note))

    def fetch_recent_videos(
        self,
        query: str = "Iran war",
        max_results_per_channel: int = 5,
        published_after: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch recent videos from monitored channels.

        Uses YouTube Data API v3 search endpoint.
        Falls back to RSS feed scraping if no API key.
        """
        if self.api_key:
            return self._fetch_via_api(query, max_results_per_channel, published_after)
        else:
            return self._fetch_via_rss(query, max_results_per_channel)

    def _fetch_via_api(self, query, max_results, published_after) -> List[Dict[str, Any]]:
        """Fetch via YouTube Data API v3."""
        try:
            import requests

            results = []
            if not published_after:
                published_after = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

            for channel_id, channel_name, credibility, bias_note in self.channels:
                try:
                    params = {
                        "part": "snippet",
                        "channelId": channel_id,
                        "q": query,
                        "type": "video",
                        "order": "date",
                        "maxResults": max_results,
                        "publishedAfter": published_after,
                        "key": self.api_key,
                    }

                    resp = requests.get(
                        "https://www.googleapis.com/youtube/v3/search",
                        params=params,
                        timeout=10,
                    )

                    if resp.status_code != 200:
                        logger.warning(f"YouTube API failed for {channel_name}: {resp.status_code}")
                        continue

                    data = resp.json()
                    for item in data.get("items", []):
                        video_id = item.get("id", {}).get("videoId", "")
                        if not video_id or video_id in self._seen_video_ids:
                            continue

                        snippet = item.get("snippet", {})
                        video = {
                            "video_id": video_id,
                            "title": snippet.get("title", ""),
                            "description": snippet.get("description", ""),
                            "channel_name": channel_name,
                            "channel_id": channel_id,
                            "published_at": snippet.get("publishedAt", ""),
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "credibility": credibility,
                            "bias_note": bias_note,
                            "transcript": None,
                        }

                        # Try to get transcript
                        transcript = self._get_transcript(video_id)
                        if transcript:
                            video["transcript"] = transcript

                        results.append(video)
                        self._seen_video_ids.add(video_id)

                except Exception as e:
                    logger.warning(f"YouTube fetch failed for {channel_name}: {e}")
                    continue

            self.last_fetch_time = datetime.now().isoformat()
            logger.info(f"YouTube API: fetched {len(results)} videos")
            return results

        except ImportError:
            logger.warning("requests not installed")
            return []

    def _fetch_via_rss(self, query, max_results) -> List[Dict[str, Any]]:
        """Fallback: fetch via YouTube RSS feeds (no API key needed)."""
        try:
            import requests
            import re as rss_re

            results = []

            for channel_id, channel_name, credibility, bias_note in self.channels:
                try:
                    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                    resp = requests.get(rss_url, timeout=10)

                    if resp.status_code != 200:
                        continue

                    # Simple XML parsing without lxml dependency
                    content = resp.text
                    entries = rss_re.findall(
                        r'<entry>(.*?)</entry>', content, rss_re.DOTALL
                    )

                    for entry_xml in entries[:max_results]:
                        video_id_match = rss_re.search(r'<yt:videoId>(.*?)</yt:videoId>', entry_xml)
                        title_match = rss_re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', entry_xml)
                        published_match = rss_re.search(r'<published>(.*?)</published>', entry_xml)

                        if not video_id_match:
                            continue

                        video_id = video_id_match.group(1)
                        if video_id in self._seen_video_ids:
                            continue

                        title = html.unescape(title_match.group(1)) if title_match else ""

                        # Filter by query keywords
                        query_lower = query.lower()
                        title_lower = title.lower()
                        keywords = query_lower.split()
                        if not any(kw in title_lower for kw in keywords):
                            continue

                        video = {
                            "video_id": video_id,
                            "title": title,
                            "description": "",
                            "channel_name": channel_name,
                            "channel_id": channel_id,
                            "published_at": published_match.group(1) if published_match else "",
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "credibility": credibility,
                            "bias_note": bias_note,
                            "transcript": None,
                        }

                        # Try to get transcript
                        transcript = self._get_transcript(video_id)
                        if transcript:
                            video["transcript"] = transcript

                        results.append(video)
                        self._seen_video_ids.add(video_id)

                except Exception as e:
                    logger.warning(f"YouTube RSS failed for {channel_name}: {e}")
                    continue

            self.last_fetch_time = datetime.now().isoformat()
            logger.info(f"YouTube RSS: fetched {len(results)} videos")
            return results

        except ImportError:
            logger.warning("requests not installed")
            return []

    def _get_transcript(self, video_id: str, languages: Optional[List[str]] = None) -> Optional[str]:
        """Get video transcript using youtube-transcript-api (no API key needed)."""
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            langs = languages or ["en", "ar", "fa", "he"]
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)

            # Combine transcript segments
            full_text = " ".join(segment["text"] for segment in transcript_list)

            # Truncate to 5000 chars for efficiency
            if len(full_text) > 5000:
                full_text = full_text[:5000] + "... [truncated]"

            return full_text

        except Exception:
            # Transcript not available — common for live streams, some videos
            return None

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "api_key_configured": self.api_key is not None,
            "channels_monitored": len(self.channels),
            "videos_seen": len(self._seen_video_ids),
            "last_fetch": self.last_fetch_time,
            "channels": [
                {"name": name, "id": cid, "credibility": cred}
                for cid, name, cred, _ in self.channels
            ],
        }


class NewsWebsiteScraper:
    """Monitors news websites via RSS feeds for breaking updates.

    No API key needed — uses public RSS feeds from major outlets.
    """

    # Pre-configured RSS feeds for Iran conflict
    DEFAULT_FEEDS = [
        # Less biased (user preference)
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "news_tier1"),
        ("Reuters World", "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best", "news_tier1"),
        ("AP News", "https://rsshub.app/apnews/topics/world-news", "news_tier1"),
        # Regional
        ("Al Jazeera Middle East", "https://www.aljazeera.com/xml/rss/all.xml", "news_tier1"),
        ("Middle East Eye", "https://www.middleeasteye.net/rss", "news_tier1"),
        ("The National (UAE)", "https://www.thenationalnews.com/rss", "news_tier2"),
        # International
        ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml", "news_tier2"),
        ("CNN World", "http://rss.cnn.com/rss/edition_world.rss", "news_tier2"),
        ("Guardian World", "https://www.theguardian.com/world/rss", "news_tier2"),
        # Analysis
        ("Foreign Affairs", "https://www.foreignaffairs.com/rss.xml", "institutional"),
        ("War on the Rocks", "https://warontherocks.com/feed/", "institutional"),
        ("CSIS", "https://www.csis.org/analysis/feed", "institutional"),
        # Economic
        ("CNBC", "https://www.cnbc.com/id/100727362/device/rss/rss.html", "news_tier2"),
        ("Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss", "news_tier2"),
        # Military/Defense
        ("Defense One", "https://www.defenseone.com/rss/", "institutional"),
        ("Breaking Defense", "https://breakingdefense.com/feed/", "institutional"),
    ]

    def __init__(self):
        self.feeds = list(self.DEFAULT_FEEDS)
        self.last_fetch_time = None
        self._seen_urls: set = set()

    def add_feed(self, name: str, url: str, credibility: str = "news_tier2"):
        """Add a news RSS feed to monitor."""
        self.feeds.append((name, url, credibility))

    def fetch_articles(
        self,
        keywords: Optional[List[str]] = None,
        max_per_feed: int = 10,
    ) -> List[Dict[str, Any]]:
        """Fetch recent articles from all RSS feeds, filtered by keywords."""
        if keywords is None:
            keywords = ["iran", "israel", "war", "strike", "missile", "hezbollah",
                        "houthi", "hormuz", "ceasefire", "nuclear", "escalat"]

        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser not installed — install with: pip install feedparser")
            return self._fetch_without_feedparser(keywords, max_per_feed)

        import re as feed_re

        results = []
        for feed_name, feed_url, credibility in self.feeds:
            try:
                feed = feedparser.parse(feed_url)

                for entry in feed.entries[:max_per_feed]:
                    url = entry.get("link", "")
                    if url in self._seen_urls:
                        continue

                    title = entry.get("title", "")
                    summary = entry.get("summary", entry.get("description", ""))
                    # Strip HTML
                    summary = feed_re.sub(r'<[^>]+>', '', summary)

                    # Filter by keywords
                    text_lower = (title + " " + summary).lower()
                    if not any(kw in text_lower for kw in keywords):
                        continue

                    results.append({
                        "title": title,
                        "content": summary[:2000],
                        "source": feed_name,
                        "url": url,
                        "timestamp": entry.get("published", entry.get("updated", "")),
                        "credibility": credibility,
                    })
                    self._seen_urls.add(url)

            except Exception as e:
                logger.warning(f"RSS feed failed for {feed_name}: {e}")
                continue

        self.last_fetch_time = datetime.now().isoformat()
        logger.info(f"News RSS: fetched {len(results)} articles from {len(self.feeds)} feeds")
        return results

    def _fetch_without_feedparser(self, keywords, max_per_feed) -> List[Dict[str, Any]]:
        """Minimal RSS fetch without feedparser dependency."""
        try:
            import requests
            import re as rss_re

            results = []
            for feed_name, feed_url, credibility in self.feeds[:5]:  # Limit without feedparser
                try:
                    resp = requests.get(feed_url, timeout=10)
                    if resp.status_code != 200:
                        continue

                    # Basic XML extraction
                    items = rss_re.findall(r'<item>(.*?)</item>', resp.text, rss_re.DOTALL)

                    for item_xml in items[:max_per_feed]:
                        title_m = rss_re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', item_xml)
                        link_m = rss_re.search(r'<link>(.*?)</link>', item_xml)

                        if not title_m:
                            continue

                        title = html.unescape(title_m.group(1))
                        text_lower = title.lower()

                        if not any(kw in text_lower for kw in keywords):
                            continue

                        url = link_m.group(1) if link_m else ""
                        if url in self._seen_urls:
                            continue

                        results.append({
                            "title": title,
                            "content": "",
                            "source": feed_name,
                            "url": url,
                            "timestamp": "",
                            "credibility": credibility,
                        })
                        self._seen_urls.add(url)

                except Exception:
                    continue

            self.last_fetch_time = datetime.now().isoformat()
            return results

        except ImportError:
            return []

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "feeds_configured": len(self.feeds),
            "articles_seen": len(self._seen_urls),
            "last_fetch": self.last_fetch_time,
        }


class GoogleNewsScraper:
    """Google News RSS — free, no API key, covers all major outlets."""

    # Topic RSS feeds (no key needed)
    TOPIC_FEEDS = {
        "iran_war": "https://news.google.com/rss/search?q=Iran+war+2026&hl=en-US&gl=US&ceid=US:en",
        "iran_israel": "https://news.google.com/rss/search?q=Iran+Israel+strikes&hl=en-US&gl=US&ceid=US:en",
        "strait_hormuz": "https://news.google.com/rss/search?q=Strait+of+Hormuz&hl=en-US&gl=US&ceid=US:en",
        "hezbollah": "https://news.google.com/rss/search?q=Hezbollah+2026&hl=en-US&gl=US&ceid=US:en",
        "houthis": "https://news.google.com/rss/search?q=Houthis+Red+Sea&hl=en-US&gl=US&ceid=US:en",
        "oil_price_war": "https://news.google.com/rss/search?q=oil+price+Iran+war&hl=en-US&gl=US&ceid=US:en",
        "iran_nuclear": "https://news.google.com/rss/search?q=Iran+nuclear+program&hl=en-US&gl=US&ceid=US:en",
        "middle_east": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRFZ4ZERBU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
    }

    def __init__(self):
        self.last_fetch_time = None
        self._seen_urls: set = set()

    def fetch_articles(self, topics: Optional[List[str]] = None, max_per_topic: int = 10) -> List[Dict[str, Any]]:
        """Fetch articles from Google News RSS feeds."""
        try:
            import requests
        except ImportError:
            logger.warning("requests not installed")
            return []

        selected_topics = topics or list(self.TOPIC_FEEDS.keys())
        results = []

        for topic in selected_topics:
            url = self.TOPIC_FEEDS.get(topic)
            if not url:
                continue

            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code != 200:
                    continue

                # Parse RSS XML
                items = re.findall(r'<item>(.*?)</item>', resp.text, re.DOTALL)
                for item_xml in items[:max_per_topic]:
                    title_m = re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', item_xml)
                    link_m = re.search(r'<link>(.*?)</link>', item_xml)
                    pubdate_m = re.search(r'<pubDate>(.*?)</pubDate>', item_xml)
                    source_m = re.search(r'<source[^>]*>(.*?)</source>', item_xml)

                    if not title_m:
                        continue

                    link = link_m.group(1) if link_m else ""
                    if link in self._seen_urls:
                        continue

                    results.append({
                        "title": html.unescape(title_m.group(1)),
                        "source": source_m.group(1) if source_m else "Google News",
                        "url": link,
                        "timestamp": pubdate_m.group(1) if pubdate_m else "",
                        "topic": topic,
                        "credibility": "news_tier2",
                    })
                    self._seen_urls.add(link)

            except Exception as e:
                logger.warning(f"Google News RSS failed for {topic}: {e}")

        self.last_fetch_time = datetime.now().isoformat()
        logger.info(f"Google News: fetched {len(results)} articles")
        return results


class WikipediaCurrentEvents:
    """Wikipedia Current Events portal — free, no API, community-curated daily summaries."""

    def __init__(self):
        self.last_fetch_time = None

    def fetch_today(self) -> Optional[Dict[str, Any]]:
        """Fetch today's current events from Wikipedia."""
        try:
            import requests

            today = datetime.utcnow()
            # Wikipedia current events URL format
            url = f"https://en.wikipedia.org/api/rest_v1/page/html/Portal:Current_events"

            resp = requests.get(url, timeout=10, headers={"User-Agent": "MiroFish/1.0"})
            if resp.status_code != 200:
                return None

            # Extract text content (strip HTML)
            text = re.sub(r'<[^>]+>', ' ', resp.text)
            text = re.sub(r'\s+', ' ', text).strip()

            # Truncate to relevant portion
            if len(text) > 8000:
                text = text[:8000] + "... [truncated]"

            self.last_fetch_time = datetime.now().isoformat()
            return {
                "title": f"Wikipedia Current Events - {today.strftime('%Y-%m-%d')}",
                "content": text,
                "source": "Wikipedia",
                "url": "https://en.wikipedia.org/wiki/Portal:Current_events",
                "timestamp": today.isoformat(),
                "credibility": "institutional",
            }

        except Exception as e:
            logger.warning(f"Wikipedia fetch failed: {e}")
            return None


class NewsDataIOScraper:
    """NewsData.io — free tier: 200 credits/day, 30+ languages, historical access."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def fetch_articles(self, query: str = "Iran war", language: str = "en", max_results: int = 10) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        try:
            import requests
            params = {
                "apikey": self.api_key,
                "q": query,
                "language": language,
                "size": min(max_results, 10),  # Free tier max 10 per request
            }
            resp = requests.get("https://newsdata.io/api/1/latest", params=params, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"NewsData.io failed: {resp.status_code}")
                return []

            data = resp.json()
            results = []
            for article in data.get("results", []):
                results.append({
                    "title": article.get("title", ""),
                    "content": article.get("description", "") or article.get("content", ""),
                    "source": article.get("source_name", ""),
                    "url": article.get("link", ""),
                    "timestamp": article.get("pubDate", ""),
                    "country": article.get("country", []),
                    "category": article.get("category", []),
                    "credibility": "news_tier2",
                })
            logger.info(f"NewsData.io: fetched {len(results)} articles")
            return results
        except Exception as e:
            logger.warning(f"NewsData.io error: {e}")
            return []


class MediastackScraper:
    """Mediastack — free tier: 100 requests/month, 7,500+ sources."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def fetch_articles(self, keywords: str = "Iran,war,Israel", limit: int = 25) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        try:
            import requests
            params = {
                "access_key": self.api_key,
                "keywords": keywords,
                "languages": "en",
                "limit": limit,
                "sort": "published_desc",
            }
            resp = requests.get("http://api.mediastack.com/v1/news", params=params, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for article in data.get("data", []):
                results.append({
                    "title": article.get("title", ""),
                    "content": article.get("description", ""),
                    "source": article.get("source", ""),
                    "url": article.get("url", ""),
                    "timestamp": article.get("published_at", ""),
                    "country": article.get("country", ""),
                    "credibility": "news_tier2",
                })
            logger.info(f"Mediastack: fetched {len(results)} articles")
            return results
        except Exception as e:
            logger.warning(f"Mediastack error: {e}")
            return []


class GNewsScraper:
    """GNews.io — free tier: 100 requests/day, 60,000+ sources."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def fetch_articles(self, query: str = "Iran war", max_results: int = 10) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []
        try:
            import requests
            params = {
                "token": self.api_key,
                "q": query,
                "lang": "en",
                "max": min(max_results, 10),
                "sortby": "publishedAt",
            }
            resp = requests.get("https://gnews.io/api/v4/search", params=params, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for article in data.get("articles", []):
                results.append({
                    "title": article.get("title", ""),
                    "content": article.get("content", article.get("description", "")),
                    "source": article.get("source", {}).get("name", ""),
                    "url": article.get("url", ""),
                    "timestamp": article.get("publishedAt", ""),
                    "credibility": "news_tier2",
                })
            logger.info(f"GNews: fetched {len(results)} articles")
            return results
        except Exception as e:
            logger.warning(f"GNews error: {e}")
            return []


class ACLEDScraper:
    """ACLED — Armed Conflict Location & Event Data. Free account required.
    Provides structured conflict event data (battles, protests, violence against civilians)."""

    def __init__(self, email: Optional[str] = None, api_key: Optional[str] = None):
        self.email = email
        self.api_key = api_key

    def fetch_events(
        self,
        country: str = "Iran",
        days_back: int = 30,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        if not self.api_key or not self.email:
            return []
        try:
            import requests
            event_date_start = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            params = {
                "key": self.api_key,
                "email": self.email,
                "country": country,
                "event_date": f"{event_date_start}|",
                "event_date_where": "BETWEEN",
                "limit": limit,
            }
            resp = requests.get("https://api.acleddata.com/acled/read", params=params, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for event in data.get("data", []):
                results.append({
                    "event_id": event.get("data_id", ""),
                    "event_date": event.get("event_date", ""),
                    "event_type": event.get("event_type", ""),
                    "sub_event_type": event.get("sub_event_type", ""),
                    "actor1": event.get("actor1", ""),
                    "actor2": event.get("actor2", ""),
                    "country": event.get("country", ""),
                    "location": event.get("location", ""),
                    "latitude": event.get("latitude", ""),
                    "longitude": event.get("longitude", ""),
                    "fatalities": event.get("fatalities", 0),
                    "notes": event.get("notes", ""),
                    "source": "ACLED",
                    "credibility": "institutional",
                })
            logger.info(f"ACLED: fetched {len(results)} conflict events for {country}")
            return results
        except Exception as e:
            logger.warning(f"ACLED error: {e}")
            return []


class OSINTManager:
    """Manages all OSINT scrapers and coordinates data ingestion."""

    def __init__(self, data_ingestor=None):
        self.data_ingestor = data_ingestor
        # Always-free sources (no API key needed)
        self.gdelt = GDELTScraper()
        self.oil_prices = OilPriceScraper()
        self.youtube = YouTubeScraper()
        self.news_websites = NewsWebsiteScraper()
        self.google_news = GoogleNewsScraper()
        self.wikipedia = WikipediaCurrentEvents()
        # Free-with-key sources
        self.news_api = None        # NewsAPI.org — 100 req/day
        self.newsdata = None        # NewsData.io — 200 credits/day
        self.mediastack = None      # Mediastack — 100 req/month
        self.gnews = None           # GNews.io — 100 req/day
        self.acled = None           # ACLED — conflict event data
        self.feeds: List[OSINTFeed] = []

    def configure(
        self,
        newsapi_key: Optional[str] = None,
        youtube_api_key: Optional[str] = None,
        newsdata_key: Optional[str] = None,
        mediastack_key: Optional[str] = None,
        gnews_key: Optional[str] = None,
        acled_email: Optional[str] = None,
        acled_key: Optional[str] = None,
        feeds: Optional[List[Dict[str, Any]]] = None,
        youtube_channels: Optional[List[Dict[str, str]]] = None,
        news_rss_feeds: Optional[List[Dict[str, str]]] = None,
    ):
        """Configure OSINT feeds. All parameters optional — unconfigured sources are skipped."""
        if newsapi_key:
            self.news_api = NewsAPIScraper(api_key=newsapi_key)
        if newsdata_key:
            self.newsdata = NewsDataIOScraper(api_key=newsdata_key)
        if mediastack_key:
            self.mediastack = MediastackScraper(api_key=mediastack_key)
        if gnews_key:
            self.gnews = GNewsScraper(api_key=gnews_key)
        if acled_key and acled_email:
            self.acled = ACLEDScraper(email=acled_email, api_key=acled_key)

        if youtube_api_key:
            self.youtube.api_key = youtube_api_key

        if youtube_channels:
            for ch in youtube_channels:
                self.youtube.add_channel(
                    ch["channel_id"], ch["name"],
                    ch.get("credibility", "news_tier2"),
                    ch.get("bias_note", ""),
                )

        if news_rss_feeds:
            for f in news_rss_feeds:
                self.news_websites.add_feed(
                    f["name"], f["url"], f.get("credibility", "news_tier2")
                )

        if feeds:
            self.feeds = [
                OSINTFeed(
                    feed_id=f.get("feed_id", f"feed_{i}"),
                    feed_name=f.get("feed_name", ""),
                    feed_type=f.get("feed_type", ""),
                    api_key=f.get("api_key"),
                    poll_interval_minutes=f.get("poll_interval_minutes", 60),
                    enabled=f.get("enabled", True),
                    params=f.get("params", {}),
                )
                for i, f in enumerate(feeds)
            ]

    def fetch_all(self, query: str = "Iran Israel war 2026") -> Dict[str, Any]:
        """Fetch from all configured OSINT sources.

        Each scraper is wrapped in try/except so a single failure
        does not prevent the remaining sources from being fetched.
        """
        results = {
            "timestamp": datetime.now().isoformat(),
            "sources": {},
        }

        # GDELT — free, no API key needed
        try:
            gdelt_articles = self.gdelt.fetch_events(query=query)
            results["sources"]["gdelt"] = {
                "count": len(gdelt_articles),
                "articles": gdelt_articles,
            }
            if self.data_ingestor and gdelt_articles:
                for article in gdelt_articles:
                    self.data_ingestor.ingest_news_article(
                        title=article.get("title", ""),
                        content=article.get("title", ""),
                        source=article.get("source", "GDELT"),
                        timestamp=article.get("timestamp", ""),
                        url=article.get("url"),
                    )
        except Exception as e:
            logger.error(f"GDELT scraper crashed in fetch_all: {e}")
            results["sources"]["gdelt"] = {"error": str(e)}

        # Oil prices
        try:
            oil_data = self.oil_prices.fetch_prices()
            results["sources"]["oil_prices"] = oil_data
        except Exception as e:
            logger.error(f"Oil price scraper crashed in fetch_all: {e}")
            results["sources"]["oil_prices"] = {"error": str(e)}

        # YouTube — free via RSS, or API if key provided
        try:
            yt_videos = self.youtube.fetch_recent_videos(query=query)
            results["sources"]["youtube"] = {
                "count": len(yt_videos),
                "videos": yt_videos,
            }
            if self.data_ingestor and yt_videos:
                for video in yt_videos:
                    # Use transcript if available, otherwise title+description
                    content = video.get("transcript") or video.get("description") or video.get("title", "")
                    self.data_ingestor.ingest_news_article(
                        title=f"[YouTube/{video.get('channel_name', '')}] {video.get('title', '')}",
                        content=content,
                        source=f"YouTube - {video.get('channel_name', '')}",
                        timestamp=video.get("published_at", ""),
                        url=video.get("url"),
                    )
        except Exception as e:
            logger.error(f"YouTube scraper crashed in fetch_all: {e}")
            results["sources"]["youtube"] = {"error": str(e)}

        # News website RSS feeds — free, no API key needed
        try:
            news_articles = self.news_websites.fetch_articles()
            results["sources"]["news_websites"] = {
                "count": len(news_articles),
                "articles": news_articles,
            }
            if self.data_ingestor and news_articles:
                for article in news_articles:
                    self.data_ingestor.ingest_news_article(
                        title=article.get("title", ""),
                        content=article.get("content", ""),
                        source=article.get("source", ""),
                        timestamp=article.get("timestamp", ""),
                        url=article.get("url"),
                    )
        except Exception as e:
            logger.error(f"News website scraper crashed in fetch_all: {e}")
            results["sources"]["news_websites"] = {"error": str(e)}

        # Google News RSS — free, no key
        try:
            gn_articles = self.google_news.fetch_articles()
            results["sources"]["google_news"] = {"count": len(gn_articles)}
            if self.data_ingestor and gn_articles:
                for article in gn_articles:
                    self.data_ingestor.ingest_news_article(
                        title=article.get("title", ""),
                        content=article.get("title", ""),  # Google News RSS only has titles
                        source=article.get("source", "Google News"),
                        timestamp=article.get("timestamp", ""),
                        url=article.get("url"),
                    )
        except Exception as e:
            logger.error(f"Google News scraper crashed in fetch_all: {e}")
            results["sources"]["google_news"] = {"error": str(e)}

        # Wikipedia Current Events — free, no key
        try:
            wiki = self.wikipedia.fetch_today()
            if wiki:
                results["sources"]["wikipedia"] = {"fetched": True}
                if self.data_ingestor:
                    self.data_ingestor.ingest_document(
                        text=wiki["content"],
                        source_name="Wikipedia Current Events",
                        category="news_article",
                        credibility="institutional",
                        timestamp=wiki["timestamp"],
                    )
        except Exception as e:
            logger.error(f"Wikipedia scraper crashed in fetch_all: {e}")
            results["sources"]["wikipedia"] = {"error": str(e)}

        # NewsAPI.org — free key, 100 req/day
        if self.news_api:
            try:
                api_articles = self.news_api.fetch_articles(
                    query=query,
                    sources="al-jazeera-english,reuters,associated-press",
                    page_size=20,
                )
                results["sources"]["news_api"] = {"count": len(api_articles)}
                if self.data_ingestor:
                    for article in api_articles:
                        self.data_ingestor.ingest_news_article(
                            title=article.get("title", ""),
                            content=article.get("content", ""),
                            source=article.get("source", ""),
                            timestamp=article.get("timestamp", ""),
                            url=article.get("url"),
                        )
            except Exception as e:
                logger.error(f"NewsAPI scraper crashed in fetch_all: {e}")
                results["sources"]["news_api"] = {"error": str(e)}

        # NewsData.io — free key, 200 credits/day
        if self.newsdata:
            try:
                nd_articles = self.newsdata.fetch_articles(query=query)
                results["sources"]["newsdata"] = {"count": len(nd_articles)}
                if self.data_ingestor:
                    for article in nd_articles:
                        self.data_ingestor.ingest_news_article(
                            title=article.get("title", ""),
                            content=article.get("content", ""),
                            source=article.get("source", "NewsData.io"),
                            timestamp=article.get("timestamp", ""),
                            url=article.get("url"),
                        )
            except Exception as e:
                logger.error(f"NewsData.io scraper crashed in fetch_all: {e}")
                results["sources"]["newsdata"] = {"error": str(e)}

        # GNews.io — free key, 100 req/day
        if self.gnews:
            try:
                gn_api_articles = self.gnews.fetch_articles(query=query)
                results["sources"]["gnews"] = {"count": len(gn_api_articles)}
                if self.data_ingestor:
                    for article in gn_api_articles:
                        self.data_ingestor.ingest_news_article(
                            title=article.get("title", ""),
                            content=article.get("content", ""),
                            source=article.get("source", "GNews"),
                            timestamp=article.get("timestamp", ""),
                            url=article.get("url"),
                        )
            except Exception as e:
                logger.error(f"GNews scraper crashed in fetch_all: {e}")
                results["sources"]["gnews"] = {"error": str(e)}

        # Mediastack — free key, 100 req/month
        if self.mediastack:
            try:
                ms_articles = self.mediastack.fetch_articles()
                results["sources"]["mediastack"] = {"count": len(ms_articles)}
                if self.data_ingestor:
                    for article in ms_articles:
                        self.data_ingestor.ingest_news_article(
                            title=article.get("title", ""),
                            content=article.get("content", ""),
                            source=article.get("source", "Mediastack"),
                            timestamp=article.get("timestamp", ""),
                            url=article.get("url"),
                        )
            except Exception as e:
                logger.error(f"Mediastack scraper crashed in fetch_all: {e}")
                results["sources"]["mediastack"] = {"error": str(e)}

        # ACLED — free account, structured conflict event data
        if self.acled:
            for country in ["Iran", "Israel", "Lebanon", "Yemen", "Iraq"]:
                try:
                    events = self.acled.fetch_events(country=country, days_back=7)
                    results["sources"][f"acled_{country.lower()}"] = {"count": len(events)}
                    if self.data_ingestor and events:
                        from .data_ingestor import DataCategory, SourceCredibility
                        self.data_ingestor.ingest_json(
                            data=events,
                            source_name=f"ACLED_{country}",
                            category=DataCategory.MILITARY_ACTION,
                            credibility=SourceCredibility.INSTITUTIONAL,
                        )
                except Exception as e:
                    logger.error(f"ACLED scraper crashed for {country} in fetch_all: {e}")
                    results["sources"][f"acled_{country.lower()}"] = {"error": str(e)}

        return results

    def get_status(self) -> Dict[str, Any]:
        """Get status of all OSINT feeds."""
        return {
            # Always free — no key needed
            "gdelt": {"enabled": True, "last_fetch": self.gdelt.last_fetch_time, "key_required": False},
            "oil_prices": {"enabled": True, "key_required": False},
            "youtube": self.youtube.get_status(),
            "news_websites": self.news_websites.get_status(),
            "google_news": {"enabled": True, "last_fetch": self.google_news.last_fetch_time, "key_required": False, "topics": len(self.google_news.TOPIC_FEEDS)},
            "wikipedia": {"enabled": True, "last_fetch": self.wikipedia.last_fetch_time, "key_required": False},
            # Free with key
            "news_api": {"enabled": self.news_api is not None, "key_required": True, "free_tier": "100 req/day"},
            "newsdata_io": {"enabled": self.newsdata is not None, "key_required": True, "free_tier": "200 credits/day"},
            "gnews": {"enabled": self.gnews is not None, "key_required": True, "free_tier": "100 req/day"},
            "mediastack": {"enabled": self.mediastack is not None, "key_required": True, "free_tier": "100 req/month"},
            "acled": {"enabled": self.acled is not None, "key_required": True, "free_tier": "free account"},
            "custom_feeds": [
                {"feed_id": f.feed_id, "feed_name": f.feed_name, "enabled": f.enabled}
                for f in self.feeds
            ],
        }
