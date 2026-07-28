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
"""Superset AI Assistant API endpoints.

All endpoints are gated by :func:`require_ai_access` (feature flag +
authentication + RBAC). The POST chat endpoints remain CSRF-exempt; cross-site
POST is mitigated by Superset's ``SameSite=Lax`` session cookie. The widget now
posts via ``SupersetClient`` (which sends ``X-CSRFToken``), so the ``@csrf.exempt``
decorators below can be dropped to enforce CSRF once verified in-browser.
"""

import logging
from collections.abc import Iterator
from typing import Any

from flask import jsonify, request, Response, stream_with_context
from flask.typing import ResponseReturnValue

from superset.ai_assistant import ai_assistant_bp
from superset.ai_assistant.agent import invoke_agent, invoke_agent_stream
from superset.ai_assistant.config import get_llm_config
from superset.ai_assistant.conversation import (
    ConversationHistory,
    get_or_create_conversation,
)
from superset.ai_assistant.security import (
    is_ai_assistant_enabled,
    require_ai_access,
    user_can_use_ai_assistant,
)
from superset.extensions import csrf
from superset.utils import json
from superset.utils.core import get_user_id

logger = logging.getLogger(__name__)


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Events frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _view_context(data: dict[str, Any]) -> dict[str, Any]:
    """Extract the optional current-view context from a request body."""
    return {
        "dashboard_id": data.get("dashboard_id"),
        "chart_id": data.get("chart_id"),
        "dataset_id": data.get("dataset_id"),
        "session_id": data.get("session_id"),
    }


@ai_assistant_bp.route("/chat", methods=["POST"])
@csrf.exempt
@require_ai_access
def chat() -> ResponseReturnValue:
    """
    Chat endpoint for AI assistant.

    Expected JSON body:
    {
        "message": "What dashboards do we have?",
        "conversation_id": "optional-existing-conversation-id",
        "session_id": "optional-session-id",
        "dashboard_id": "optional-current-dashboard-id",
        "chart_id": "optional-current-chart-id",
        "dataset_id": "optional-current-dataset-id"
    }

    Returns:
        JSON response with AI assistant's answer and conversation_id for future requests
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON body provided"}), 400

        message = data.get("message", "").strip()
        if not message:
            return jsonify({"error": "Message is required"}), 400

        context = _view_context(data)
        conversation = get_or_create_conversation(
            data.get("conversation_id"), user_id=get_user_id(), context=context
        )

        # Invoke the agent with context and conversation history
        result = invoke_agent(
            message, context=context, conversation_history=conversation
        )

        return jsonify(result), 200 if result.get("success") else 500

    except Exception as e:
        logger.error("Chat endpoint error: %s", e, exc_info=True)
        return jsonify(
            {
                "success": False,
                "error": "Internal server error",
                "response": "An unexpected error occurred.",
            }
        ), 500


@ai_assistant_bp.route("/chat/stream", methods=["POST"])
@csrf.exempt
@require_ai_access
def chat_stream() -> ResponseReturnValue:
    """Streaming (SSE) variant of /chat.

    Emits Server-Sent Events as the agent generates its answer:
      - `event: token` with `{"delta": "..."}` for each incremental chunk
      - `event: trace_step` with `{"id", "tool", "label", "status": "running"|"done"|"error"}`
        as each MCP tool call starts/finishes
      - `event: done`  with `{"conversation_id": "...", "verification_note": "..."}`
      - `event: error` with `{"error": "..."}`

    Same request body as /chat (message, conversation_id, session_id,
    dashboard_id, chart_id, dataset_id).
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Message is required"}), 400

    context = _view_context(data)
    conversation = get_or_create_conversation(
        data.get("conversation_id"), user_id=get_user_id(), context=context
    )

    def generate() -> Iterator[str]:
        try:
            for event_type, payload in invoke_agent_stream(
                message, context=context, conversation_history=conversation
            ):
                if event_type == "token":
                    yield _sse("token", {"delta": payload})
                elif event_type == "trace_step":
                    yield _sse("trace_step", payload)
                elif event_type == "done":
                    yield _sse("done", payload)
                elif event_type == "error":
                    yield _sse("error", {"error": payload})
        except Exception as e:  # noqa: BLE001 - headers already sent; report via SSE
            logger.error("Chat stream error: %s", e, exc_info=True)
            yield _sse("error", {"error": "Internal server error"})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # Disable nginx proxy_buffering for this response so tokens flush live.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@ai_assistant_bp.route("/config", methods=["GET"])
def config() -> ResponseReturnValue:
    """
    Get AI assistant configuration and LLM provider info.

    Reports whether the feature is enabled and whether the current user is
    authorized, so the frontend can decide whether to render the widget.

    Returns:
        JSON with current configuration (provider, model, settings)
    """
    try:
        enabled = is_ai_assistant_enabled()
        payload: dict[str, Any] = {
            "success": True,
            "enabled": enabled,
            "authorized": enabled and user_can_use_ai_assistant(),
        }
        if enabled:
            llm_config = get_llm_config()
            payload["config"] = llm_config
            payload["message"] = f"Using {llm_config['provider']} as LLM provider"
        return jsonify(payload), 200

    except Exception as e:
        logger.error("Config endpoint error: %s", e, exc_info=True)
        return jsonify(
            {
                "success": False,
                "error": str(e),
            }
        ), 500


@ai_assistant_bp.route("/health", methods=["GET"])
def health() -> ResponseReturnValue:
    """
    Health check endpoint for AI assistant.

    Returns:
        JSON with health status and LLM provider availability
    """
    try:
        from superset.ai_assistant.config import get_llm_instance

        # Try to instantiate LLM to verify configuration
        try:
            llm = get_llm_instance()
            llm_status = "ok"
            # Use .model attribute (works with ChatOpenAI and ChatAnthropic)
            model_name = getattr(llm, "model", "unknown")
            llm_message = f"LLM ready: {model_name}"
        except ValueError as e:
            llm_status = "error"
            llm_message = f"LLM not configured: {str(e)}"

        return jsonify(
            {
                "success": True,
                "status": "ok",
                "llm_status": llm_status,
                "llm_message": llm_message,
            }
        ), 200

    except Exception as e:
        logger.error("Health check error: %s", e, exc_info=True)
        return jsonify(
            {
                "success": False,
                "status": "error",
                "error": str(e),
            }
        ), 500


@ai_assistant_bp.route("/conversations", methods=["GET"])
@require_ai_access
def list_conversations() -> ResponseReturnValue:
    """List the current user's conversations, most-recent first.

    Optional ``context_key`` query param filters to a single view context
    (e.g. ``chart:5``), powering the per-chart conversation list.
    """
    try:
        context_key = request.args.get("context_key")
        conversations = ConversationHistory.list_for_user(
            get_user_id(), context_key=context_key
        )
        return jsonify(
            {
                "success": True,
                "total": len(conversations),
                "conversations": conversations,
            }
        ), 200

    except Exception as e:
        logger.error("List conversations error: %s", e, exc_info=True)
        return jsonify(
            {
                "success": False,
                "error": str(e),
            }
        ), 500


@ai_assistant_bp.route("/conversations/<conversation_id>", methods=["GET"])
@require_ai_access
def get_conversation(conversation_id: str) -> ResponseReturnValue:
    """
    Get a conversation's messages by ID (scoped to the current user).

    Args:
        conversation_id: ID of the conversation

    Returns:
        JSON with conversation messages
    """
    try:
        messages = ConversationHistory.fetch_messages(conversation_id, get_user_id())
        if messages is None:
            return jsonify({"success": False, "error": "Not found"}), 404

        return jsonify(
            {
                "success": True,
                "conversation_id": conversation_id,
                "message_count": len(messages),
                "messages": messages,
            }
        ), 200

    except Exception as e:
        logger.error("Get conversation error: %s", e, exc_info=True)
        return jsonify(
            {
                "success": False,
                "error": str(e),
            }
        ), 500
