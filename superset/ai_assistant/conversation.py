#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Conversation history management for the AI Assistant.

Backed by the ``ai_conversations`` / ``ai_conversation_messages`` tables so
threads are durable across workers and restarts and can be scoped to a user and
a view context (chart/dashboard/dataset). The full transcript is stored; only a
bounded tail is replayed into the agent per turn to keep prompt size — and
therefore latency and cost — in check.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from superset.ai_assistant.models import AiConversation, AiConversationMessage
from superset.extensions import db

logger = logging.getLogger(__name__)

# Conversations untouched for longer than this may be pruned by cleanup_expired.
CONVERSATION_EXPIRY_HOURS = 24 * 30  # 30 days

# Maximum number of prior (non-system) messages replayed into the agent per turn.
# The full transcript is still stored; only the tail is sent so prompt size —
# and therefore latency and cost — stays bounded on long conversations.
MAX_CONTEXT_MESSAGES = 20


def _to_uuid(value: Any) -> Optional[uuid.UUID]:
    """Coerce a value to a UUID, returning None if it isn't a valid UUID."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


class ConversationHistory:
    """Manages a single AI assistant conversation, persisted to the database."""

    def __init__(
        self,
        conversation_id: Optional[str] = None,
        user_id: Optional[int] = None,
        context: Optional[dict[str, Any]] = None,
    ):
        """Load an existing conversation or create a new one.

        Args:
            conversation_id: Optional id of an existing conversation. If it is
                missing, malformed, or not owned by ``user_id``, a fresh
                conversation is created instead.
            user_id: Owner of the conversation (from the authenticated user).
            context: Optional view context used to label a new conversation
                (keys: dashboard_id / chart_id / dataset_id).
        """
        self.user_id = user_id
        conv = self._load_owned(conversation_id, user_id) if conversation_id else None
        if conv is None:
            conv = self._create(user_id, context)
        self.conversation_id = str(conv.uuid)

    @staticmethod
    def _load_owned(
        conversation_id: Optional[str], user_id: Optional[int]
    ) -> Optional[AiConversation]:
        """Return the conversation if it exists and belongs to the user."""
        conv_uuid = _to_uuid(conversation_id)
        if conv_uuid is None:
            return None
        conv = db.session.get(AiConversation, conv_uuid)
        if conv is None:
            return None
        # Only allow access to the caller's own conversations (or legacy
        # unowned ones) to avoid leaking transcripts across users.
        if conv.user_id is not None and user_id is not None and conv.user_id != user_id:
            logger.warning(
                "Refusing access to conversation %s owned by another user",
                conversation_id,
            )
            return None
        return conv

    @staticmethod
    def _create(
        user_id: Optional[int], context: Optional[dict[str, Any]]
    ) -> AiConversation:
        context_key, context_label = _context_identity(context or {})
        conv = AiConversation(
            user_id=user_id,
            context_key=context_key,
            context_label=context_label,
        )
        db.session.add(conv)
        _safe_commit()
        logger.info("Created new conversation: %s", conv.uuid)
        return conv

    def _conversation(self) -> Optional[AiConversation]:
        conv_uuid = _to_uuid(self.conversation_id)
        if conv_uuid is None:
            return None
        return db.session.get(AiConversation, conv_uuid)

    def add_message(self, role: str, content: str) -> None:
        """Append a message to the conversation and persist it."""
        conv = self._conversation()
        if conv is None:
            logger.warning(
                "Conversation %s no longer exists; skipping message",
                self.conversation_id,
            )
            return
        db.session.add(
            AiConversationMessage(conversation_id=conv.uuid, role=role, content=content)
        )
        conv.changed_on = datetime.now()
        _safe_commit()
        logger.debug(
            "Added %s message to conversation %s: %s...",
            role,
            self.conversation_id,
            content[:50],
        )

    def get_messages(self) -> list[dict[str, Any]]:
        """Return all messages (role, content, timestamp) for this conversation."""
        conv = self._conversation()
        if conv is None:
            return []
        return [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": (m.created_on or datetime.now()).isoformat(),
            }
            for m in conv.messages
        ]

    def get_conversation_context(self) -> list[dict[str, str]]:
        """Return the recent message window formatted for the agent.

        Excludes system messages (the agent supplies its own system prompt) and
        keeps only the most recent ``MAX_CONTEXT_MESSAGES`` messages.
        """
        context = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in self.get_messages()
            if msg["role"] != "system"
        ]
        return context[-MAX_CONTEXT_MESSAGES:]

    def clear(self) -> None:
        """Delete this conversation and its messages."""
        if (conv := self._conversation()) is not None:
            db.session.delete(conv)
            _safe_commit()
            logger.info("Cleared conversation: %s", self.conversation_id)

    @staticmethod
    def cleanup_expired() -> None:
        """Remove conversations untouched beyond ``CONVERSATION_EXPIRY_HOURS``."""
        cutoff = datetime.now() - timedelta(hours=CONVERSATION_EXPIRY_HOURS)
        expired = (
            db.session.query(AiConversation)
            .filter(AiConversation.changed_on < cutoff)
            .all()
        )
        for conv in expired:
            db.session.delete(conv)
        if expired:
            _safe_commit()
            logger.info("Cleaned up %d expired conversations", len(expired))

    @classmethod
    def fetch_messages(
        cls, conversation_id: str, user_id: Optional[int]
    ) -> Optional[list[dict[str, Any]]]:
        """Return an owned conversation's messages, or None if not found.

        Read-only: unlike the constructor, this never creates a conversation.
        """
        conv = cls._load_owned(conversation_id, user_id)
        if conv is None:
            return None
        return [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": (m.created_on or datetime.now()).isoformat(),
            }
            for m in conv.messages
        ]

    @staticmethod
    def list_for_user(
        user_id: Optional[int], context_key: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Return conversation summaries for a user, most-recent first."""
        query = db.session.query(AiConversation)
        if user_id is not None:
            query = query.filter(AiConversation.user_id == user_id)
        if context_key is not None:
            query = query.filter(AiConversation.context_key == context_key)
        conversations = query.order_by(AiConversation.changed_on.desc()).all()
        return [
            {
                "conversation_id": str(conv.uuid),
                "context_key": conv.context_key,
                "context_label": conv.context_label,
                "title": conv.title,
                "message_count": len(conv.messages),
                "created_on": (conv.created_on or datetime.now()).isoformat(),
                "changed_on": (conv.changed_on or datetime.now()).isoformat(),
            }
            for conv in conversations
        ]


def _context_identity(context: dict[str, Any]) -> tuple[str, str]:
    """Derive a stable (context_key, context_label) from a view context."""
    if context.get("chart_id") is not None:
        return f"chart:{context['chart_id']}", f"Chart {context['chart_id']}"
    if context.get("dashboard_id") is not None:
        return (
            f"dashboard:{context['dashboard_id']}",
            f"Dashboard {context['dashboard_id']}",
        )
    if context.get("dataset_id") is not None:
        return f"dataset:{context['dataset_id']}", f"Dataset {context['dataset_id']}"
    return "global", "General"


def _safe_commit() -> None:
    """Commit, rolling back on error so a persistence failure can't corrupt
    the session or abort an in-flight streamed response.

    Intentionally uses manual commit/rollback (not the @transaction decorator)
    so best-effort history persistence never raises into the chat response.
    """
    # pylint: disable=consider-using-transaction
    try:
        db.session.commit()
    except Exception:  # noqa: BLE001 - history persistence is best-effort
        logger.exception("Failed to persist AI conversation change")
        db.session.rollback()


def get_or_create_conversation(
    conversation_id: Optional[str] = None,
    user_id: Optional[int] = None,
    context: Optional[dict[str, Any]] = None,
) -> ConversationHistory:
    """Get an existing (owned) conversation or create a new one.

    Args:
        conversation_id: Optional id of an existing conversation.
        user_id: Owner of the conversation (authenticated user id).
        context: Optional view context used to label a new conversation.

    Returns:
        ConversationHistory instance
    """
    return ConversationHistory(conversation_id, user_id=user_id, context=context)
