# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""add_ai_assistant_conversations

Create tables backing the AI Assistant's persistent chat history:
- ai_conversations: one row per conversation thread, scoped to a user and an
  optional view context key (chart/dashboard/dataset/global).
- ai_conversation_messages: the messages within each conversation.

Revision ID: a1b2c3d4e5f6
Revises: 4b2a8c9d3e1f
Create Date: 2026-07-23 00:00:00.000000

"""

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy_utils import UUIDType

from superset.migrations.shared.utils import (
    create_fks_for_table,
    create_index,
    create_table,
    drop_fks_for_table,
    drop_index,
    drop_table,
)

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "4b2a8c9d3e1f"

CONVERSATIONS_TABLE = "ai_conversations"
MESSAGES_TABLE = "ai_conversation_messages"


def upgrade():
    create_table(
        CONVERSATIONS_TABLE,
        Column("uuid", UUIDType(binary=True), primary_key=True),
        Column("user_id", Integer, nullable=True),
        Column("context_key", String(255), nullable=True),
        Column("context_label", String(255), nullable=True),
        Column("title", String(255), nullable=True),
        Column("created_on", DateTime, nullable=True),
        Column("changed_on", DateTime, nullable=True),
    )
    create_index(
        CONVERSATIONS_TABLE, "idx_ai_conversations_user_id", ["user_id"]
    )
    create_index(
        CONVERSATIONS_TABLE, "idx_ai_conversations_context_key", ["context_key"]
    )
    create_fks_for_table(
        foreign_key_name="fk_ai_conversations_user_id_ab_user",
        table_name=CONVERSATIONS_TABLE,
        referenced_table="ab_user",
        local_cols=["user_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )

    create_table(
        MESSAGES_TABLE,
        Column("id", Integer, primary_key=True),
        Column("conversation_id", UUIDType(binary=True), nullable=False),
        Column("role", String(32), nullable=False),
        Column("content", Text, nullable=False),
        Column("created_on", DateTime, nullable=True),
    )
    create_index(
        MESSAGES_TABLE,
        "idx_ai_conversation_messages_conversation_id",
        ["conversation_id"],
    )
    create_fks_for_table(
        foreign_key_name="fk_ai_conv_messages_conversation_id_ai_conversations",
        table_name=MESSAGES_TABLE,
        referenced_table=CONVERSATIONS_TABLE,
        local_cols=["conversation_id"],
        remote_cols=["uuid"],
        ondelete="CASCADE",
    )


def downgrade():
    drop_fks_for_table(
        MESSAGES_TABLE,
        ["fk_ai_conv_messages_conversation_id_ai_conversations"],
    )
    drop_index(MESSAGES_TABLE, "idx_ai_conversation_messages_conversation_id")
    drop_table(MESSAGES_TABLE)

    drop_fks_for_table(
        CONVERSATIONS_TABLE, ["fk_ai_conversations_user_id_ab_user"]
    )
    drop_index(CONVERSATIONS_TABLE, "idx_ai_conversations_context_key")
    drop_index(CONVERSATIONS_TABLE, "idx_ai_conversations_user_id")
    drop_table(CONVERSATIONS_TABLE)
