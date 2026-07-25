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
"""SQLAlchemy models backing the AI Assistant's persistent chat history.

Conversations are scoped to a user (``user_id``) and an optional view
``context_key`` (e.g. ``chart:5`` / ``dashboard:1``) so the frontend can list
prior threads per chart/dashboard and resume them across sessions, workers, and
restarts — replacing the process-local in-memory store.
"""

import uuid
from datetime import datetime

from flask_appbuilder import Model
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy_utils import UUIDType


class AiConversation(Model):
    """A single AI Assistant conversation thread owned by a user."""

    __tablename__ = "ai_conversations"

    uuid = Column(UUIDType(binary=True), default=uuid.uuid4, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("ab_user.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Stable key identifying the view the conversation belongs to
    # (e.g. "chart:5", "dashboard:1", "dataset:9", or "global").
    context_key = Column(String(255), nullable=True, index=True)
    context_label = Column(String(255), nullable=True)
    title = Column(String(255), nullable=True)
    created_on = Column(DateTime, default=datetime.now, nullable=True)
    changed_on = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=True
    )

    messages = relationship(
        "AiConversationMessage",
        back_populates="conversation",
        order_by="AiConversationMessage.id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AiConversationMessage(Model):
    """A single message within an :class:`AiConversation`."""

    __tablename__ = "ai_conversation_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(
        UUIDType(binary=True),
        ForeignKey("ai_conversations.uuid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    created_on = Column(DateTime, default=datetime.now, nullable=True)

    conversation = relationship("AiConversation", back_populates="messages")
