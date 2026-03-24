"""
Official Social Media Scraper for Geopolitical Intelligence.

Scrapes real tweets/posts from heads of state and senior officials.
These are treated as highest-credibility official communications —
modern leaders use social media as de facto policy channels.

Supports:
- Twitter/X API: Official government accounts
- Telegram API: Iranian/Hezbollah channels
- Government RSS feeds: White House, Kremlin, MFA press releases

Each post is tagged with source_actor, credibility_level, timestamp,
and topic_classification (LLM-classified).
"""

import json
import logging
import os
import time
import re
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger('mirofish.social_media_scraper')


@dataclass
class OfficialAccount:
    """Configuration for an official account to scrape."""
    actor_id: str               # Maps to simulation actor
    actor_name: str
    platform: str               # twitter, telegram, rss
    account_id: str             # @handle, channel ID, or RSS URL
    credibility: str = "official"
    poll_interval_minutes: int = 15
    enabled: bool = True
    last_scraped: Optional[str] = None
    last_post_id: Optional[str] = None


@dataclass
class ScrapedPost:
    """A single scraped post from an official account."""
    post_id: str
    actor_id: str
    actor_name: str
    platform: str
    content: str
    timestamp: str
    url: Optional[str] = None
    media_urls: List[str] = field(default_factory=list)
    engagement: Dict[str, int] = field(default_factory=dict)
    reply_to: Optional[str] = None
    is_repost: bool = False
    topic_classification: Optional[str] = None  # LLM-classified

    def to_dict(self) -> Dict[str, Any]:
        return {
            "post_id": self.post_id,
            "actor_id": self.actor_id,
            "actor_name": self.actor_name,
            "platform": self.platform,
            "content": self.content,
            "timestamp": self.timestamp,
            "url": self.url,
            "engagement": self.engagement,
            "is_repost": self.is_repost,
            "topic_classification": self.topic_classification,
        }


# Pre-configured official accounts for Iran conflict
DEFAULT_ACCOUNTS: List[Dict[str, Any]] = [
    # US Officials
    {"actor_id": "usa", "actor_name": "POTUS", "platform": "twitter", "account_id": "@POTUS"},
    {"actor_id": "usa", "actor_name": "SecDef", "platform": "twitter", "account_id": "@SecDef"},
    {"actor_id": "usa", "actor_name": "CENTCOM", "platform": "twitter", "account_id": "@CENTCOM"},
    {"actor_id": "usa", "actor_name": "Trump Truth Social", "platform": "truthsocial", "account_id": "@realDonaldTrump"},
    # Israeli Officials
    {"actor_id": "israel", "actor_name": "Netanyahu", "platform": "twitter", "account_id": "@netanyahu"},
    {"actor_id": "israel", "actor_name": "IDF Spokesperson", "platform": "twitter", "account_id": "@IDF"},
    {"actor_id": "israel", "actor_name": "Israel MFA", "platform": "twitter", "account_id": "@IsraelMFA"},
    # Iranian Officials/Media
    {"actor_id": "iran", "actor_name": "Khamenei Office", "platform": "twitter", "account_id": "@khaboronline"},
    {"actor_id": "iran", "actor_name": "Iran MFA", "platform": "twitter", "account_id": "@ABORONLINE"},
    {"actor_id": "iran", "actor_name": "Tasnim News", "platform": "telegram", "account_id": "tasaboronline"},
    {"actor_id": "iran", "actor_name": "IRGC Media", "platform": "telegram", "account_id": "seaboronline"},
    # Russian Officials
    {"actor_id": "russia", "actor_name": "Russia MFA", "platform": "twitter", "account_id": "@maboronline"},
    {"actor_id": "russia", "actor_name": "Kremlin", "platform": "rss", "account_id": "http://en.kremlin.ru/events/president/news.rss"},
    # Chinese Officials
    {"actor_id": "china", "actor_name": "China MFA Spokesperson", "platform": "twitter", "account_id": "@MFA_China"},
    # Hezbollah
    {"actor_id": "hezbollah", "actor_name": "Al-Manar TV", "platform": "telegram", "account_id": "almanaboronline"},
    # Houthis
    {"actor_id": "houthis", "actor_name": "Houthi Military", "platform": "telegram", "account_id": "military_houthi"},
]


class SocialMediaScraper:
    """Scrapes official social media accounts for geopolitical intelligence."""

    def __init__(
        self,
        twitter_bearer_token: Optional[str] = None,
        telegram_api_id: Optional[str] = None,
        telegram_api_hash: Optional[str] = None,
        data_ingestor=None,
        llm_client=None,
    ):
        self.twitter_bearer_token = twitter_bearer_token
        self.telegram_api_id = telegram_api_id
        self.telegram_api_hash = telegram_api_hash
        self.data_ingestor = data_ingestor
        self.llm_client = llm_client

        self.accounts: List[OfficialAccount] = []
        self._scraped_posts: Dict[str, ScrapedPost] = {}  # post_id -> post
        self._running = False

    def configure_accounts(self, accounts: Optional[List[Dict[str, Any]]] = None):
        """Configure accounts to scrape. Uses defaults if none provided."""
        account_configs = accounts or DEFAULT_ACCOUNTS
        self.accounts = []
        for config in account_configs:
            self.accounts.append(OfficialAccount(
                actor_id=config["actor_id"],
                actor_name=config["actor_name"],
                platform=config["platform"],
                account_id=config["account_id"],
                credibility=config.get("credibility", "official"),
                poll_interval_minutes=config.get("poll_interval_minutes", 15),
                enabled=config.get("enabled", True),
            ))
        logger.info(f"Configured {len(self.accounts)} accounts for scraping")

    def scrape_twitter(self, account: OfficialAccount, max_results: int = 20) -> List[ScrapedPost]:
        """Scrape tweets from an official Twitter/X account.

        Requires twitter_bearer_token to be set.
        Uses Twitter API v2 user timeline endpoint.
        """
        if not self.twitter_bearer_token:
            logger.warning("Twitter bearer token not configured — skipping Twitter scrape")
            return []

        try:
            import requests

            handle = account.account_id.lstrip("@")

            # Step 1: Get user ID from handle
            headers = {"Authorization": f"Bearer {self.twitter_bearer_token}"}
            user_resp = requests.get(
                f"https://api.twitter.com/2/users/by/username/{handle}",
                headers=headers,
                timeout=10,
            )

            if user_resp.status_code == 401:
                logger.error(f"Twitter bearer token is invalid or expired (401 Unauthorized)")
                self.twitter_bearer_token = None  # Disable further attempts with bad token
                return []
            if user_resp.status_code == 429:
                retry_after = user_resp.headers.get("Retry-After", "60")
                logger.warning(f"Twitter rate limited for {handle}. Retry after {retry_after}s")
                return []
            if user_resp.status_code != 200:
                logger.error(f"Twitter user lookup failed for {handle}: {user_resp.status_code}")
                return []

            user_id = user_resp.json().get("data", {}).get("id")
            if not user_id:
                return []

            # Step 2: Get recent tweets
            params = {
                "max_results": max_results,
                "tweet.fields": "created_at,public_metrics,referenced_tweets",
            }
            if account.last_post_id:
                params["since_id"] = account.last_post_id

            tweets_resp = requests.get(
                f"https://api.twitter.com/2/users/{user_id}/tweets",
                headers=headers,
                params=params,
                timeout=10,
            )

            if tweets_resp.status_code != 200:
                logger.error(f"Twitter timeline failed for {handle}: {tweets_resp.status_code}")
                return []

            tweets_data = tweets_resp.json().get("data", [])
            posts = []

            for tweet in tweets_data:
                metrics = tweet.get("public_metrics", {})
                is_repost = any(
                    ref.get("type") == "retweeted"
                    for ref in (tweet.get("referenced_tweets") or [])
                )

                post = ScrapedPost(
                    post_id=tweet["id"],
                    actor_id=account.actor_id,
                    actor_name=account.actor_name,
                    platform="twitter",
                    content=tweet.get("text", ""),
                    timestamp=tweet.get("created_at", ""),
                    url=f"https://twitter.com/{handle}/status/{tweet['id']}",
                    engagement={
                        "likes": metrics.get("like_count", 0),
                        "retweets": metrics.get("retweet_count", 0),
                        "replies": metrics.get("reply_count", 0),
                    },
                    is_repost=is_repost,
                )
                posts.append(post)
                self._scraped_posts[post.post_id] = post

            # Update last scraped
            if posts:
                account.last_post_id = posts[0].post_id
            account.last_scraped = datetime.now().isoformat()

            logger.info(f"Scraped {len(posts)} tweets from @{handle}")
            return posts

        except ImportError:
            logger.error("requests library not installed")
            return []
        except Exception as e:
            logger.error(f"Twitter scrape failed for {account.account_id}: {e}")
            return []

    def scrape_telegram(self, account: OfficialAccount, limit: int = 20) -> List[ScrapedPost]:
        """Scrape messages from a Telegram channel.

        Requires telegram_api_id and telegram_api_hash.
        Uses Telethon library for Telegram API access.
        """
        if not self.telegram_api_id or not self.telegram_api_hash:
            logger.warning("Telegram API credentials not configured — skipping")
            return []

        try:
            int(self.telegram_api_id)
        except (ValueError, TypeError):
            logger.error(f"Telegram API ID must be numeric, got: {self.telegram_api_id!r}")
            return []

        try:
            from telethon.sync import TelegramClient
            from telethon.tl.functions.messages import GetHistoryRequest

            posts = []

            import tempfile
            session_dir = os.path.join(os.path.expanduser("~"), ".mirofish")
            os.makedirs(session_dir, exist_ok=True)
            session_path = os.path.join(session_dir, "telegram_scraper_session")
            with TelegramClient(session_path, int(self.telegram_api_id), self.telegram_api_hash) as client:
                channel = client.get_entity(account.account_id)
                messages = client.get_messages(channel, limit=limit)

                for msg in messages:
                    if not msg.text:
                        continue

                    post = ScrapedPost(
                        post_id=f"tg_{account.account_id}_{msg.id}",
                        actor_id=account.actor_id,
                        actor_name=account.actor_name,
                        platform="telegram",
                        content=msg.text,
                        timestamp=msg.date.isoformat() if msg.date else "",
                        url=f"https://t.me/{account.account_id}/{msg.id}",
                        engagement={"views": msg.views or 0},
                    )
                    posts.append(post)
                    self._scraped_posts[post.post_id] = post

            account.last_scraped = datetime.now().isoformat()
            logger.info(f"Scraped {len(posts)} messages from Telegram/{account.account_id}")
            return posts

        except ImportError:
            logger.warning("telethon not installed — skipping Telegram scrape")
            return []
        except Exception as e:
            logger.error(f"Telegram scrape failed for {account.account_id}: {e}")
            return []

    def scrape_rss(self, account: OfficialAccount, max_entries: int = 20) -> List[ScrapedPost]:
        """Scrape entries from an RSS feed (government press releases)."""
        try:
            import feedparser

            feed = feedparser.parse(account.account_id)
            if feed.bozo and not feed.entries:
                logger.warning(f"RSS feed returned malformed data for {account.account_id}: {feed.bozo_exception}")
                return []
            posts = []

            for entry in getattr(feed, 'entries', [])[:max_entries]:
                content = entry.get("summary", entry.get("description", ""))
                # Strip HTML tags
                content = re.sub(r'<[^>]+>', '', content)

                post = ScrapedPost(
                    post_id=hashlib.md5(entry.get("link", entry.get("title", "")).encode()).hexdigest()[:16],
                    actor_id=account.actor_id,
                    actor_name=account.actor_name,
                    platform="rss",
                    content=content,
                    timestamp=entry.get("published", ""),
                    url=entry.get("link", ""),
                )
                posts.append(post)
                self._scraped_posts[post.post_id] = post

            account.last_scraped = datetime.now().isoformat()
            logger.info(f"Scraped {len(posts)} entries from RSS/{account.actor_name}")
            return posts

        except ImportError:
            logger.warning("feedparser not installed — skipping RSS scrape")
            return []
        except Exception as e:
            logger.error(f"RSS scrape failed for {account.account_id}: {e}")
            return []

    def scrape_account(self, account: OfficialAccount) -> List[ScrapedPost]:
        """Scrape a single account based on its platform."""
        if not account.enabled:
            return []

        if account.platform == "twitter":
            return self.scrape_twitter(account)
        elif account.platform == "telegram":
            return self.scrape_telegram(account)
        elif account.platform == "rss":
            return self.scrape_rss(account)
        elif account.platform == "truthsocial":
            # Truth Social doesn't have a public API — would need custom scraping
            logger.info(f"Truth Social scraping not yet implemented for {account.account_id}")
            return []
        else:
            logger.warning(f"Unknown platform: {account.platform}")
            return []

    def scrape_all(self) -> Dict[str, List[ScrapedPost]]:
        """Scrape all configured accounts. Returns actor_id -> posts mapping.

        Includes a small delay between accounts to avoid hammering APIs.
        """
        results: Dict[str, List[ScrapedPost]] = {}

        for i, account in enumerate(self.accounts):
            # Rate limit: 1 second delay between accounts to avoid API abuse
            if i > 0:
                time.sleep(1)
            posts = self.scrape_account(account)
            if posts:
                if account.actor_id not in results:
                    results[account.actor_id] = []
                results[account.actor_id].extend(posts)

                # Auto-ingest into data ingestor if available
                if self.data_ingestor:
                    for post in posts:
                        self.data_ingestor.ingest_official_statement(
                            actor_id=post.actor_id,
                            actor_name=post.actor_name,
                            statement=post.content,
                            platform=post.platform,
                            timestamp=post.timestamp,
                            url=post.url,
                        )

        return results

    def classify_topics(self, posts: List[ScrapedPost]) -> List[ScrapedPost]:
        """Use LLM to classify post topics (military, diplomatic, economic, threat, de-escalation)."""
        if not self.llm_client:
            return posts

        for post in posts:
            if post.topic_classification:
                continue
            try:
                response = self.llm_client.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Classify this official statement into one category: "
                                "military, diplomatic, economic, threat, de-escalation, "
                                "domestic, humanitarian, information_warfare. "
                                "Respond with just the category name."
                            ),
                        },
                        {"role": "user", "content": post.content[:500]},
                    ],
                    temperature=0.1,
                    max_tokens=20,
                )
                post.topic_classification = response.strip().lower()
            except Exception:
                post.topic_classification = "unclassified"

        return posts

    def get_status(self) -> Dict[str, Any]:
        """Get scraper status for all configured accounts."""
        return {
            "total_accounts": len(self.accounts),
            "enabled_accounts": sum(1 for a in self.accounts if a.enabled),
            "total_scraped_posts": len(self._scraped_posts),
            "accounts": [
                {
                    "actor_id": a.actor_id,
                    "actor_name": a.actor_name,
                    "platform": a.platform,
                    "account_id": a.account_id,
                    "enabled": a.enabled,
                    "last_scraped": a.last_scraped,
                    "poll_interval_minutes": a.poll_interval_minutes,
                }
                for a in self.accounts
            ],
        }
