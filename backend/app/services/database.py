"""
PostgreSQL persistence layer for Fors8.

Stores conversations, messages, predictions, and agent memories.
Degrades gracefully: if PostgreSQL is unavailable the rest of the
application continues to work without persistence.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger('fors8.database')

try:
    import psycopg2
    import psycopg2.extras
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False
    logger.warning("psycopg2 not installed -- database persistence disabled")


class Database:
    """Thin wrapper around psycopg2 for Fors8 persistence.

    Every public method catches connection / query errors so that callers
    never have to worry about PostgreSQL being down.
    """

    def __init__(self, dsn: Optional[str] = None):
        self._dsn = dsn or os.environ.get(
            'DATABASE_URL',
            'dbname=fors8 user=joelc host=localhost',
        )
        self._conn = None

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _get_conn(self):
        """Return an open connection, reconnecting if necessary."""
        if not _HAS_PSYCOPG2:
            return None
        try:
            if self._conn is None or self._conn.closed:
                self._conn = psycopg2.connect(self._dsn)
                self._conn.autocommit = True
            return self._conn
        except Exception as exc:
            logger.error("PostgreSQL connection failed: %s", exc)
            self._conn = None
            return None

    def _cursor(self):
        conn = self._get_conn()
        if conn is None:
            return None
        try:
            return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        except Exception as exc:
            logger.error("Failed to create cursor: %s", exc)
            return None

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def create_conversation(self, title: str) -> Optional[str]:
        """Insert a new conversation row and return its id."""
        cur = self._cursor()
        if cur is None:
            return None
        try:
            conv_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO conversations (id, title, created_at) VALUES (%s, %s, %s)",
                (conv_id, title, datetime.utcnow()),
            )
            return conv_id
        except Exception as exc:
            logger.error("create_conversation failed: %s", exc)
            return None

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Return a single conversation with its messages."""
        cur = self._cursor()
        if cur is None:
            return None
        try:
            cur.execute(
                "SELECT id, title, created_at FROM conversations WHERE id = %s",
                (conversation_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            conv = dict(row)
            conv['created_at'] = conv['created_at'].isoformat() if conv.get('created_at') else None
            conv['messages'] = self.get_messages(conversation_id) or []
            return conv
        except Exception as exc:
            logger.error("get_conversation failed: %s", exc)
            return None

    def list_conversations(self) -> List[Dict[str, Any]]:
        """Return all conversations with message counts, newest first."""
        cur = self._cursor()
        if cur is None:
            return []
        try:
            cur.execute("""
                SELECT
                    c.id,
                    c.title,
                    c.created_at,
                    COUNT(m.id)      AS message_count,
                    MAX(m.content)   AS last_message
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                GROUP BY c.id, c.title, c.created_at
                ORDER BY c.created_at DESC
            """)
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d['created_at'] = d['created_at'].isoformat() if d.get('created_at') else None
                result.append(d)
            return result
        except Exception as exc:
            logger.error("list_conversations failed: %s", exc)
            return []

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and its associated messages."""
        cur = self._cursor()
        if cur is None:
            return False
        try:
            cur.execute("DELETE FROM messages WHERE conversation_id = %s", (conversation_id,))
            cur.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            return True
        except Exception as exc:
            logger.error("delete_conversation failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        prediction_id: Optional[str] = None,
    ) -> Optional[str]:
        """Append a message to a conversation."""
        cur = self._cursor()
        if cur is None:
            return None
        try:
            msg_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO messages (id, conversation_id, role, content, prediction_id, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (msg_id, conversation_id, role, content, prediction_id, datetime.utcnow()),
            )
            return msg_id
        except Exception as exc:
            logger.error("add_message failed: %s", exc)
            return None

    def get_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Return messages for a conversation ordered by time."""
        cur = self._cursor()
        if cur is None:
            return []
        try:
            cur.execute(
                """SELECT id, role, content, prediction_id, created_at
                   FROM messages
                   WHERE conversation_id = %s
                   ORDER BY created_at ASC""",
                (conversation_id,),
            )
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d['created_at'] = d['created_at'].isoformat() if d.get('created_at') else None
                result.append(d)
            return result
        except Exception as exc:
            logger.error("get_messages failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Predictions
    # ------------------------------------------------------------------

    def save_prediction(self, prediction_data: Dict[str, Any]) -> Optional[str]:
        """Persist a prediction dict. Returns prediction_id."""
        cur = self._cursor()
        if cur is None:
            return None
        try:
            pred_id = prediction_data.get('prediction_id', str(uuid.uuid4()))
            cur.execute(
                """INSERT INTO predictions (id, data, created_at)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data""",
                (pred_id, json.dumps(prediction_data, default=str), datetime.utcnow()),
            )
            return pred_id
        except Exception as exc:
            logger.error("save_prediction failed: %s", exc)
            return None

    def update_prediction(self, prediction_id: str, updates: Dict[str, Any]) -> bool:
        """Merge *updates* into the stored prediction JSON."""
        cur = self._cursor()
        if cur is None:
            return False
        try:
            cur.execute("SELECT data FROM predictions WHERE id = %s", (prediction_id,))
            row = cur.fetchone()
            if not row:
                return False
            existing = json.loads(row['data']) if isinstance(row['data'], str) else row['data']
            existing.update(updates)
            cur.execute(
                "UPDATE predictions SET data = %s WHERE id = %s",
                (json.dumps(existing, default=str), prediction_id),
            )
            return True
        except Exception as exc:
            logger.error("update_prediction failed: %s", exc)
            return False

    def get_prediction(self, prediction_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single prediction by id."""
        cur = self._cursor()
        if cur is None:
            return None
        try:
            cur.execute("SELECT id, data, created_at FROM predictions WHERE id = %s", (prediction_id,))
            row = cur.fetchone()
            if not row:
                return None
            data = json.loads(row['data']) if isinstance(row['data'], str) else row['data']
            data['_created_at'] = row['created_at'].isoformat() if row.get('created_at') else None
            return data
        except Exception as exc:
            logger.error("get_prediction failed: %s", exc)
            return None

    def get_predictions_for_conversation(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Return all predictions linked to a conversation via its messages."""
        cur = self._cursor()
        if cur is None:
            return []
        try:
            cur.execute(
                """SELECT DISTINCT p.id, p.data, p.created_at
                   FROM predictions p
                   JOIN messages m ON m.prediction_id = p.id
                   WHERE m.conversation_id = %s
                   ORDER BY p.created_at ASC""",
                (conversation_id,),
            )
            rows = cur.fetchall()
            result = []
            for row in rows:
                data = json.loads(row['data']) if isinstance(row['data'], str) else row['data']
                data['_created_at'] = row['created_at'].isoformat() if row.get('created_at') else None
                result.append(data)
            return result
        except Exception as exc:
            logger.error("get_predictions_for_conversation failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Agent Memories
    # ------------------------------------------------------------------

    def save_memory(
        self,
        actor_id: str,
        content: str,
        memory_type: str,
        source_prediction_id: Optional[str] = None,
        round_num: Optional[int] = None,
    ) -> Optional[str]:
        """Store an agent memory entry."""
        cur = self._cursor()
        if cur is None:
            return None
        try:
            mem_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO agent_memories
                   (id, actor_id, content, memory_type, source_prediction_id, round_num, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (mem_id, actor_id, content, memory_type, source_prediction_id, round_num, datetime.utcnow()),
            )
            return mem_id
        except Exception as exc:
            logger.error("save_memory failed: %s", exc)
            return None

    def get_memories(self, actor_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent memories for an actor, newest first."""
        cur = self._cursor()
        if cur is None:
            return []
        try:
            cur.execute(
                """SELECT content, memory_type, created_at
                   FROM agent_memories
                   WHERE actor_id = %s
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (actor_id, limit),
            )
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d['created_at'] = d['created_at'].isoformat() if d.get('created_at') else None
                result.append(d)
            return result
        except Exception as exc:
            logger.error("get_memories failed: %s", exc)
            return []

    def get_all_memories_for_prediction(self, prediction_id: str) -> List[Dict[str, Any]]:
        """Return every memory generated by a specific prediction run."""
        cur = self._cursor()
        if cur is None:
            return []
        try:
            cur.execute(
                """SELECT actor_id, content, memory_type, round_num, created_at
                   FROM agent_memories
                   WHERE source_prediction_id = %s
                   ORDER BY round_num ASC, created_at ASC""",
                (prediction_id,),
            )
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d['created_at'] = d['created_at'].isoformat() if d.get('created_at') else None
                result.append(d)
            return result
        except Exception as exc:
            logger.error("get_all_memories_for_prediction failed: %s", exc)
            return []


# ------------------------------------------------------------------
# Module-level singleton so all callers share one connection
# ------------------------------------------------------------------
_db_instance: Optional[Database] = None


def get_db() -> Database:
    """Return (and lazily create) the module-level Database singleton."""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
