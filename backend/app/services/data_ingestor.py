"""
Data Ingestor Service for Geopolitical Conflict Simulation.

Handles ingestion of diverse data sources into the Zep knowledge graph:
- Structured data (JSON/CSV): military capabilities, economic indicators
- Unstructured documents: intelligence reports, news articles, historical analyses
- Pre-built data packages: Iran conflict actor profiles, initial conditions
- Source credibility tagging: official > semi-official > news > social media

All data is converted to Zep EpisodeData format and fed into the knowledge graph.
"""

import csv
import io
import json
import os
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger('mirofish.data_ingestor')


class SourceCredibility(str, Enum):
    """Source credibility levels for ingested data."""
    OFFICIAL = "official"              # Government statements, official documents
    SEMI_OFFICIAL = "semi_official"    # State-affiliated media, military spokespersons
    INSTITUTIONAL = "institutional"    # Think tanks, SIPRI, IISS, World Bank
    NEWS_TIER1 = "news_tier1"          # Al Jazeera, Reuters, AP (less biased per user)
    NEWS_TIER2 = "news_tier2"          # CNN, BBC, etc.
    OSINT = "osint"                    # Open-source intelligence, satellite imagery
    SOCIAL_MEDIA = "social_media"      # Social media posts (non-official)
    UNVERIFIED = "unverified"          # Unverified sources


class DataCategory(str, Enum):
    """Categories of ingested data."""
    MILITARY_CAPABILITY = "military_capability"
    ECONOMIC_INDICATOR = "economic_indicator"
    POLITICAL_EVENT = "political_event"
    DIPLOMATIC_ACTION = "diplomatic_action"
    MILITARY_ACTION = "military_action"
    INTELLIGENCE_REPORT = "intelligence_report"
    OFFICIAL_STATEMENT = "official_statement"
    NEWS_ARTICLE = "news_article"
    HISTORICAL_ANALOGY = "historical_analogy"
    SATELLITE_IMAGERY = "satellite_imagery"
    WEAPONS_SYSTEM = "weapons_system"
    CASUALTY_REPORT = "casualty_report"
    ENERGY_INFRASTRUCTURE = "energy_infrastructure"


@dataclass
class IngestedRecord:
    """A single ingested data record."""
    record_id: str = ""
    source: str = ""
    source_credibility: SourceCredibility = SourceCredibility.UNVERIFIED
    category: DataCategory = DataCategory.NEWS_ARTICLE
    title: str = ""
    content: str = ""
    timestamp: str = ""
    actors_mentioned: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_episode_text(self) -> str:
        """Convert to natural language text for Zep EpisodeData."""
        parts = []
        if self.title:
            parts.append(f"[{self.category.value.upper()}] {self.title}")
        if self.content:
            parts.append(self.content)
        if self.actors_mentioned:
            parts.append(f"Actors involved: {', '.join(self.actors_mentioned)}")
        if self.source:
            parts.append(f"Source: {self.source} (credibility: {self.source_credibility.value})")
        if self.timestamp:
            parts.append(f"Date: {self.timestamp}")
        return "\n".join(parts)


@dataclass
class IngestionResult:
    """Result of a data ingestion operation."""
    success: bool = True
    records_ingested: int = 0
    records_failed: int = 0
    errors: List[str] = field(default_factory=list)
    source_id: str = ""


class DataIngestor:
    """Ingests diverse data sources into Zep knowledge graph."""

    def __init__(self, zep_client=None, graph_id: Optional[str] = None):
        self.zep_client = zep_client
        self.graph_id = graph_id
        self._ingested_sources: Dict[str, Dict[str, Any]] = {}

    def ingest_json(
        self,
        data: List[Dict[str, Any]],
        source_name: str,
        category: DataCategory,
        credibility: SourceCredibility = SourceCredibility.INSTITUTIONAL,
        actor_field: str = "actor",
    ) -> IngestionResult:
        """Ingest structured JSON data (e.g., military capabilities, economic indicators).

        Args:
            data: List of dictionaries with structured data
            source_name: Name of the data source
            category: Data category
            credibility: Source credibility level
            actor_field: Field name containing actor identifier
        """
        result = IngestionResult(source_id=source_name)
        records = []

        for i, item in enumerate(data):
            try:
                record = IngestedRecord(
                    record_id=f"{source_name}_{i}",
                    source=source_name,
                    source_credibility=credibility,
                    category=category,
                    title=item.get("title", item.get("name", f"Record {i}")),
                    content=json.dumps(item, ensure_ascii=False, indent=2),
                    timestamp=item.get("timestamp", item.get("date", datetime.now().isoformat())),
                    actors_mentioned=[item[actor_field]] if actor_field in item else [],
                    metadata=item,
                )
                records.append(record)
                result.records_ingested += 1
            except Exception as e:
                result.records_failed += 1
                result.errors.append(f"Record {i}: {str(e)}")

        # Send to Zep
        if self.zep_client and self.graph_id and records:
            self._send_to_zep(records, source_name)

        self._track_source(source_name, category, credibility, result.records_ingested)
        return result

    def ingest_csv(
        self,
        csv_content: str,
        source_name: str,
        category: DataCategory,
        credibility: SourceCredibility = SourceCredibility.INSTITUTIONAL,
    ) -> IngestionResult:
        """Ingest CSV data (e.g., SIPRI arms transfers, economic time series)."""
        result = IngestionResult(source_id=source_name)
        records = []

        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            for i, row in enumerate(reader):
                record = IngestedRecord(
                    record_id=f"{source_name}_csv_{i}",
                    source=source_name,
                    source_credibility=credibility,
                    category=category,
                    title=f"{source_name} row {i}",
                    content="; ".join(f"{k}: {v}" for k, v in row.items() if v),
                    timestamp=row.get("date", row.get("year", "")),
                    metadata=dict(row),
                )
                records.append(record)
                result.records_ingested += 1
        except Exception as e:
            result.success = False
            result.errors.append(f"CSV parse error: {str(e)}")

        if self.zep_client and self.graph_id and records:
            self._send_to_zep(records, source_name)

        self._track_source(source_name, category, credibility, result.records_ingested)
        return result

    def ingest_document(
        self,
        text: str,
        source_name: str,
        category: DataCategory,
        credibility: SourceCredibility = SourceCredibility.NEWS_TIER1,
        actors_mentioned: Optional[List[str]] = None,
        timestamp: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest an unstructured document (intelligence report, news article, etc.)."""
        result = IngestionResult(source_id=source_name)

        record = IngestedRecord(
            record_id=f"{source_name}_doc",
            source=source_name,
            source_credibility=credibility,
            category=category,
            title=source_name,
            content=text,
            timestamp=timestamp or datetime.now().isoformat(),
            actors_mentioned=actors_mentioned or [],
        )

        result.records_ingested = 1

        if self.zep_client and self.graph_id:
            self._send_to_zep([record], source_name)

        self._track_source(source_name, category, credibility, 1)
        return result

    def ingest_official_statement(
        self,
        actor_id: str,
        actor_name: str,
        statement: str,
        platform: str,
        timestamp: str,
        url: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest an official statement from a head of state or senior official.

        These are highest-credibility data — leaders' social media posts are
        de facto official communications.
        """
        result = IngestionResult(source_id=f"official_{actor_id}_{timestamp}")

        record = IngestedRecord(
            record_id=f"official_{actor_id}_{timestamp}",
            source=f"{actor_name} ({platform})",
            source_credibility=SourceCredibility.OFFICIAL,
            category=DataCategory.OFFICIAL_STATEMENT,
            title=f"Official statement by {actor_name}",
            content=statement,
            timestamp=timestamp,
            actors_mentioned=[actor_id],
            metadata={
                "platform": platform,
                "url": url,
                "actor_id": actor_id,
                "is_official_communication": True,
            },
        )

        result.records_ingested = 1

        if self.zep_client and self.graph_id:
            self._send_to_zep([record], f"official_{actor_id}")

        return result

    def ingest_news_article(
        self,
        title: str,
        content: str,
        source: str,
        timestamp: str,
        actors_mentioned: Optional[List[str]] = None,
        url: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest a news article with automatic credibility classification."""
        # Determine credibility based on source
        tier1_sources = {
            "al jazeera", "reuters", "ap", "associated press",
            "afp", "bbc arabic", "al arabiya",
        }
        tier2_sources = {
            "cnn", "bbc", "nyt", "new york times", "washington post",
            "guardian", "times of israel", "haaretz",
        }

        source_lower = source.lower()
        if any(t1 in source_lower for t1 in tier1_sources):
            credibility = SourceCredibility.NEWS_TIER1
        elif any(t2 in source_lower for t2 in tier2_sources):
            credibility = SourceCredibility.NEWS_TIER2
        elif "iran" in source_lower and ("press tv" in source_lower or "tasnim" in source_lower or "fars" in source_lower):
            credibility = SourceCredibility.SEMI_OFFICIAL
        elif "idf" in source_lower or "centcom" in source_lower:
            credibility = SourceCredibility.SEMI_OFFICIAL
        else:
            credibility = SourceCredibility.NEWS_TIER2

        result = IngestionResult(source_id=f"news_{hash(title) % 100000}")

        record = IngestedRecord(
            record_id=result.source_id,
            source=source,
            source_credibility=credibility,
            category=DataCategory.NEWS_ARTICLE,
            title=title,
            content=content,
            timestamp=timestamp,
            actors_mentioned=actors_mentioned or [],
            metadata={"url": url, "source_name": source},
        )

        result.records_ingested = 1

        if self.zep_client and self.graph_id:
            self._send_to_zep([record], f"news_{source}")

        return result

    def ingest_data_package(
        self,
        package_dir: str,
    ) -> IngestionResult:
        """Ingest a pre-built data package (e.g., backend/data/iran_conflict/).

        Reads actors.json, initial_conditions.json, and any other JSON files
        in the directory and ingests them all.
        """
        result = IngestionResult(source_id=f"package_{os.path.basename(package_dir)}")

        if not os.path.isdir(package_dir):
            result.success = False
            result.errors.append(f"Directory not found: {package_dir}")
            return result

        for filename in sorted(os.listdir(package_dir)):
            if not filename.endswith('.json'):
                continue

            filepath = os.path.join(package_dir, filename)
            if os.path.isdir(filepath):
                continue

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Determine category from filename
                if "actors" in filename:
                    category = DataCategory.MILITARY_CAPABILITY
                elif "conditions" in filename:
                    category = DataCategory.POLITICAL_EVENT
                elif "military" in filename or "capabilities" in filename:
                    category = DataCategory.MILITARY_CAPABILITY
                elif "economic" in filename:
                    category = DataCategory.ECONOMIC_INDICATOR
                elif "proxy" in filename:
                    category = DataCategory.INTELLIGENCE_REPORT
                elif "historical" in filename or "analog" in filename:
                    category = DataCategory.HISTORICAL_ANALOGY
                elif "demands" in filename:
                    category = DataCategory.DIPLOMATIC_ACTION
                else:
                    category = DataCategory.INTELLIGENCE_REPORT

                if isinstance(data, list):
                    sub_result = self.ingest_json(
                        data, filename, category, SourceCredibility.INSTITUTIONAL
                    )
                else:
                    sub_result = self.ingest_document(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        filename, category, SourceCredibility.INSTITUTIONAL,
                    )

                result.records_ingested += sub_result.records_ingested
                result.records_failed += sub_result.records_failed
                result.errors.extend(sub_result.errors)

                logger.info(f"Ingested {filename}: {sub_result.records_ingested} records")

            except Exception as e:
                result.records_failed += 1
                result.errors.append(f"Failed to ingest {filename}: {str(e)}")

        # Ingest scenario templates subdirectory
        templates_dir = os.path.join(package_dir, "scenario_templates")
        if os.path.isdir(templates_dir):
            for tpl_file in sorted(os.listdir(templates_dir)):
                if not tpl_file.endswith('.json'):
                    continue
                try:
                    with open(os.path.join(templates_dir, tpl_file), 'r', encoding='utf-8') as f:
                        tpl_data = json.load(f)
                    sub_result = self.ingest_document(
                        json.dumps(tpl_data, ensure_ascii=False, indent=2),
                        f"scenario_template/{tpl_file}",
                        DataCategory.INTELLIGENCE_REPORT,
                        SourceCredibility.INSTITUTIONAL,
                    )
                    result.records_ingested += sub_result.records_ingested
                except Exception as e:
                    result.errors.append(f"Template {tpl_file}: {str(e)}")

        return result

    def list_sources(self) -> List[Dict[str, Any]]:
        """List all ingested data sources."""
        return [
            {
                "source_id": source_id,
                **info,
            }
            for source_id, info in self._ingested_sources.items()
        ]

    def remove_source(self, source_id: str) -> bool:
        """Remove a data source tracking entry."""
        if source_id in self._ingested_sources:
            del self._ingested_sources[source_id]
            return True
        return False

    def _send_to_zep(self, records: List[IngestedRecord], source_name: str):
        """Send records to Zep as EpisodeData."""
        if not self.zep_client or not self.graph_id:
            return

        try:
            from zep_cloud.types import EpisodeData

            episodes = []
            for record in records:
                episode = EpisodeData(
                    text=record.to_episode_text(),
                    source="data_ingestor",
                    source_description=f"{record.source} ({record.source_credibility.value})",
                    reference=record.record_id,
                )
                episodes.append(episode)

            # Send in batches of 5
            batch_size = 5
            for i in range(0, len(episodes), batch_size):
                batch = episodes[i:i + batch_size]
                self.zep_client.graph.add_batch(
                    graph_id=self.graph_id,
                    episodes=batch,
                )

            logger.info(f"Sent {len(episodes)} episodes to Zep from {source_name}")

        except ImportError:
            logger.warning("zep_cloud not installed — skipping Zep ingestion")
        except Exception as e:
            logger.error(f"Zep ingestion failed for {source_name}: {e}")

    def _track_source(
        self, source_name: str, category,
        credibility, record_count: int
    ):
        """Track ingested sources for listing/management."""
        cat_val = category.value if hasattr(category, 'value') else str(category)
        cred_val = credibility.value if hasattr(credibility, 'value') else str(credibility)
        self._ingested_sources[source_name] = {
            "category": cat_val,
            "credibility": cred_val,
            "record_count": record_count,
            "ingested_at": datetime.now().isoformat(),
        }
