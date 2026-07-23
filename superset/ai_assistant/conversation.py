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
"""Conversation history management for AI Assistant.

Stores and retrieves conversation messages to maintain context across requests.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

# In-memory conversation storage (alternatively, can be extended to use database/Redis)
_conversation_store: dict[str, dict[str, Any]] = {}

# Conversation expiry time (24 hours)
CONVERSATION_EXPIRY_HOURS = 24


class ConversationHistory:
    """Manages conversation history for the AI assistant."""

    def __init__(self, conversation_id: Optional[str] = None):
        """Initialize conversation history.
        
        Args:
            conversation_id: Optional ID for existing conversation.
                            If None, a new conversation ID is generated.
        """
        if conversation_id:
            self.conversation_id = conversation_id
            self._ensure_conversation_exists()
        else:
            self.conversation_id = str(uuid.uuid4())
            _conversation_store[self.conversation_id] = {
                "messages": [],
                "created_at": datetime.now(),
                "last_accessed": datetime.now(),
            }
            logger.info(f"Created new conversation: {self.conversation_id}")

    def _ensure_conversation_exists(self) -> None:
        """Ensure conversation exists or create it."""
        if self.conversation_id not in _conversation_store:
            _conversation_store[self.conversation_id] = {
                "messages": [],
                "created_at": datetime.now(),
                "last_accessed": datetime.now(),
            }

    def add_message(self, role: str, content: str) -> None:
        """Add a message to conversation history.
        
        Args:
            role: Message role ("user", "assistant", "system")
            content: Message content
        """
        if self.conversation_id not in _conversation_store:
            self._ensure_conversation_exists()

        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        
        _conversation_store[self.conversation_id]["messages"].append(message)
        _conversation_store[self.conversation_id]["last_accessed"] = datetime.now()
        
        logger.debug(
            f"Added {role} message to conversation {self.conversation_id}: "
            f"{content[:50]}..."
        )

    def get_messages(self) -> list[dict[str, str]]:
        """Get all messages in conversation.
        
        Returns:
            List of message dicts with role and content
        """
        if self.conversation_id not in _conversation_store:
            return []
        
        messages = _conversation_store[self.conversation_id]["messages"]
        _conversation_store[self.conversation_id]["last_accessed"] = datetime.now()
        
        return messages

    def get_conversation_context(self) -> list[dict[str, str]]:
        """Get messages formatted for agent context.
        
        Excludes system messages and formats for LangChain agent.
        
        Returns:
            List of messages (role, content) for agent
        """
        messages = self.get_messages()
        # Filter out system messages (they'll be re-added by agent)
        return [
            {
                "role": msg["role"],
                "content": msg["content"]
            }
            for msg in messages
            if msg["role"] != "system"
        ]

    def clear(self) -> None:
        """Clear conversation history."""
        if self.conversation_id in _conversation_store:
            del _conversation_store[self.conversation_id]
            logger.info(f"Cleared conversation: {self.conversation_id}")

    @staticmethod
    def cleanup_expired() -> None:
        """Remove expired conversations (>24 hours old)."""
        now = datetime.now()
        expired_ids = []
        
        for conv_id, conv_data in _conversation_store.items():
            last_accessed = conv_data.get("last_accessed", now)
            age = now - last_accessed
            
            if age > timedelta(hours=CONVERSATION_EXPIRY_HOURS):
                expired_ids.append(conv_id)
        
        for conv_id in expired_ids:
            del _conversation_store[conv_id]
            logger.info(f"Cleaned up expired conversation: {conv_id}")
        
        if expired_ids:
            logger.info(f"Cleaned up {len(expired_ids)} expired conversations")

    @staticmethod
    def get_all_conversations() -> dict[str, dict[str, Any]]:
        """Get all conversations (for debugging/monitoring).
        
        Returns:
            Dictionary of conversation_id -> conversation_data
        """
        return {
            conv_id: {
                "message_count": len(conv_data["messages"]),
                "created_at": conv_data["created_at"].isoformat(),
                "last_accessed": conv_data["last_accessed"].isoformat(),
            }
            for conv_id, conv_data in _conversation_store.items()
        }


def get_or_create_conversation(conversation_id: Optional[str] = None) -> ConversationHistory:
    """Get existing or create new conversation.
    
    Args:
        conversation_id: Optional ID for existing conversation
        
    Returns:
        ConversationHistory instance
    """
    ConversationHistory.cleanup_expired()
    return ConversationHistory(conversation_id)
