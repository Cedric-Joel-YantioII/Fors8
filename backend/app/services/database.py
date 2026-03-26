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

    def create_conversation(self, title: str) -> Optional[Dict[str, Any]]:
        """Insert a new conversation row and return it as a dict."""
        cur = self._cursor()
        if cur is None:
            return None
        try:
            now = datetime.utcnow()
            cur.execute(
                "INSERT INTO conversations (title, created_at, updated_at) VALUES (%s, %s, %s) RETURNING id, title, created_at, updated_at",
                (title, now, now),
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "title": row["title"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                }
            return None
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
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = %s",
                (conversation_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            conv = dict(row)
            conv['created_at'] = conv['created_at'].isoformat() if conv.get('created_at') else None
            conv['updated_at'] = conv['updated_at'].isoformat() if conv.get('updated_at') else None
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
                    c.updated_at,
                    COUNT(m.id)  AS message_count,
                    (SELECT m2.content FROM messages m2
                     WHERE m2.conversation_id = c.id
                     ORDER BY m2.created_at DESC LIMIT 1) AS last_message
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                GROUP BY c.id, c.title, c.created_at, c.updated_at
                ORDER BY COALESCE(c.updated_at, c.created_at) DESC
            """)
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d['created_at'] = d['created_at'].isoformat() if d.get('created_at') else None
                d['updated_at'] = d['updated_at'].isoformat() if d.get('updated_at') else None
                result.append(d)
            return result
        except Exception as exc:
            logger.error("list_conversations failed: %s", exc)
            return []

    def update_conversation(self, conversation_id: str, **kwargs) -> bool:
        """Update conversation fields (e.g. title). Returns True on success."""
        cur = self._cursor()
        if cur is None:
            return False
        try:
            # Build SET clause from kwargs (only allow safe column names)
            allowed = {'title', 'updated_at'}
            sets = []
            values = []
            for k, v in kwargs.items():
                if k in allowed:
                    sets.append(f"{k} = %s")
                    values.append(v)
            if not sets:
                return False
            # Always bump updated_at
            if 'updated_at' not in kwargs:
                sets.append("updated_at = %s")
                values.append(datetime.utcnow())
            values.append(conversation_id)
            cur.execute(
                f"UPDATE conversations SET {', '.join(sets)} WHERE id = %s",
                tuple(values),
            )
            return True
        except Exception as exc:
            logger.error("update_conversation failed: %s", exc)
            return False

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
    ) -> Optional[Dict[str, Any]]:
        """Append a message to a conversation. Returns the message as a dict."""
        cur = self._cursor()
        if cur is None:
            return None
        try:
            now = datetime.utcnow()
            cur.execute(
                """INSERT INTO messages (conversation_id, role, content, prediction_id, created_at)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING id""",
                (conversation_id, role, content, prediction_id, now),
            )
            row = cur.fetchone()
            msg_id = row["id"] if row else None
            # Also bump the conversation's updated_at timestamp
            cur.execute(
                "UPDATE conversations SET updated_at = %s WHERE id = %s",
                (now, conversation_id),
            )
            return {
                "id": msg_id,
                "role": role,
                "content": content,
                "prediction_id": prediction_id,
                "created_at": now.isoformat(),
            }
        except Exception as exc:
            logger.error("add_message failed: %s", exc)
            return None

    def update_message(self, message_id: str, **kwargs) -> bool:
        """Update message fields (e.g. prediction_id). Returns True on success."""
        cur = self._cursor()
        if cur is None:
            return False
        try:
            allowed = {'prediction_id', 'content', 'role'}
            sets = []
            values = []
            for k, v in kwargs.items():
                if k in allowed:
                    sets.append(f"{k} = %s")
                    values.append(v)
            if not sets:
                return False
            values.append(message_id)
            cur.execute(
                f"UPDATE messages SET {', '.join(sets)} WHERE id = %s",
                tuple(values),
            )
            return True
        except Exception as exc:
            logger.error("update_message failed: %s", exc)
            return False

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
        """Persist a prediction dict (upsert). Returns prediction_id."""
        cur = self._cursor()
        if cur is None:
            return None
        try:
            pred_id = prediction_data.get('prediction_id', str(uuid.uuid4()))
            cur.execute(
                """INSERT INTO predictions (id, question, status, progress_pct, progress_message,
                       model_name, num_agents, num_runs, outcomes, actor_results, answers,
                       gpu_cost, error, graph_id, social_results, agent_decisions,
                       grounding_score, grounding_report, scenario_type,
                       created_at, completed_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET
                       status = EXCLUDED.status,
                       progress_pct = EXCLUDED.progress_pct,
                       progress_message = EXCLUDED.progress_message,
                       outcomes = EXCLUDED.outcomes,
                       actor_results = EXCLUDED.actor_results,
                       answers = EXCLUDED.answers,
                       gpu_cost = EXCLUDED.gpu_cost,
                       error = EXCLUDED.error,
                       graph_id = EXCLUDED.graph_id,
                       social_results = EXCLUDED.social_results,
                       agent_decisions = EXCLUDED.agent_decisions,
                       grounding_score = EXCLUDED.grounding_score,
                       grounding_report = EXCLUDED.grounding_report,
                       scenario_type = EXCLUDED.scenario_type,
                       completed_at = EXCLUDED.completed_at""",
                (
                    pred_id,
                    prediction_data.get('question', ''),
                    prediction_data.get('status', 'queued'),
                    prediction_data.get('progress_pct', 0),
                    prediction_data.get('progress_message', ''),
                    prediction_data.get('model_name', ''),
                    prediction_data.get('num_agents', 0),
                    prediction_data.get('num_runs', 0),
                    json.dumps(prediction_data.get('outcomes', {}), default=str),
                    json.dumps(prediction_data.get('actor_results', {}), default=str),
                    json.dumps(prediction_data.get('answers', {}), default=str),
                    prediction_data.get('gpu_cost', 0),
                    prediction_data.get('error', ''),
                    prediction_data.get('graph_id', ''),
                    json.dumps(prediction_data.get('social_results'), default=str) if prediction_data.get('social_results') else None,
                    json.dumps(prediction_data.get('agent_decisions'), default=str) if prediction_data.get('agent_decisions') else None,
                    prediction_data.get('grounding_score'),
                    json.dumps(prediction_data.get('grounding_report'), default=str) if prediction_data.get('grounding_report') else None,
                    prediction_data.get('scenario_type', ''),
                    prediction_data.get('created_at') or datetime.utcnow(),
                    prediction_data.get('completed_at') or None,
                ),
            )
            return pred_id
        except Exception as exc:
            logger.error("save_prediction failed: %s", exc)
            return None

    def update_prediction(self, prediction_id: str, updates: Dict[str, Any]) -> bool:
        """Update specific fields on a prediction row."""
        cur = self._cursor()
        if cur is None:
            return False
        try:
            # Map of allowed fields to their SQL types (jsonb fields need json.dumps)
            jsonb_fields = {'outcomes', 'actor_results', 'answers',
                            'social_results', 'agent_decisions', 'grounding_report'}
            allowed = {'question', 'status', 'progress_pct', 'progress_message',
                       'model_name', 'num_agents', 'num_runs', 'outcomes',
                       'actor_results', 'answers', 'gpu_cost', 'error',
                       'graph_id', 'social_results', 'agent_decisions',
                       'grounding_score', 'grounding_report', 'scenario_type',
                       'completed_at'}
            sets = []
            vals = []
            for k, v in updates.items():
                if k not in allowed:
                    continue
                sets.append(f"{k} = %s")
                vals.append(json.dumps(v, default=str) if k in jsonb_fields else v)
            if not sets:
                return True  # nothing to update
            vals.append(prediction_id)
            cur.execute(
                f"UPDATE predictions SET {', '.join(sets)} WHERE id = %s",
                vals,
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
            cur.execute("SELECT * FROM predictions WHERE id = %s", (prediction_id,))
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d['prediction_id'] = d.pop('id', prediction_id)
            d['created_at'] = d['created_at'].isoformat() if d.get('created_at') else None
            d['completed_at'] = d['completed_at'].isoformat() if d.get('completed_at') else None
            return d
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
                """SELECT DISTINCT p.*
                   FROM predictions p
                   JOIN messages m ON m.prediction_id = p.id
                   WHERE m.conversation_id = %s
                   ORDER BY p.created_at ASC""",
                (conversation_id,),
            )
            rows = cur.fetchall()
            result = []
            for row in rows:
                d = dict(row)
                d['prediction_id'] = d.pop('id')
                d['created_at'] = d['created_at'].isoformat() if d.get('created_at') else None
                d['completed_at'] = d['completed_at'].isoformat() if d.get('completed_at') else None
                result.append(d)
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
