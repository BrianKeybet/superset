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
"""Superset AI Assistant API endpoints."""

import logging

from flask import jsonify, request
from superset.extensions import csrf

from superset.ai_assistant import ai_assistant_bp
from superset.ai_assistant.agent import invoke_agent
from superset.ai_assistant.config import get_llm_config
from superset.ai_assistant.conversation import get_or_create_conversation
from superset.extensions import db

logger = logging.getLogger(__name__)


@ai_assistant_bp.route("/chat", methods=["POST"])
@csrf.exempt
def chat():
    """
    Chat endpoint for AI assistant.

    Expected JSON body:
    {
        "message": "What dashboards do we have?",
        "conversation_id": "optional-existing-conversation-id",
        "session_id": "optional-session-id",
        "dashboard_id": "optional-current-dashboard-id",
        "chart_id": "optional-current-chart-id"
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

        # TODO: Add authentication check
        # if not security_manager.is_authenticated():
        #     return jsonify({"error": "User must be authenticated"}), 401

        # Get or create conversation for this chat session
        conversation_id = data.get("conversation_id")
        conversation = get_or_create_conversation(conversation_id)

        # Extract optional context about current view
        context = {
            "dashboard_id": data.get("dashboard_id"),
            "chart_id": data.get("chart_id"),
            "session_id": data.get("session_id")
        }

        # Invoke the agent with context and conversation history
        result = invoke_agent(message, context=context, conversation_history=conversation)

        return jsonify(result), 200 if result.get("success") else 500

    except Exception as e:
        logger.error(f"Chat endpoint error: {e}", exc_info=True)
        return jsonify(
            {
                "success": False,
                "error": "Internal server error",
                "response": "An unexpected error occurred.",
            }
        ), 500


@ai_assistant_bp.route("/config", methods=["GET"])
def config():
    """
    Get AI assistant configuration and LLM provider info.

    Returns:
        JSON with current configuration (provider, model, settings)
    """
    try:
        llm_config = get_llm_config()
        return jsonify(
            {
                "success": True,
                "config": llm_config,
                "message": f"Using {llm_config['provider']} as LLM provider",
            }
        ), 200

    except Exception as e:
        logger.error(f"Config endpoint error: {e}", exc_info=True)
        return jsonify(
            {
                "success": False,
                "error": str(e),
            }
        ), 500


@ai_assistant_bp.route("/health", methods=["GET"])
def health():
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
            model_name = getattr(llm, 'model', 'unknown')
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
        logger.error(f"Health check error: {e}", exc_info=True)
        return jsonify(
            {
                "success": False,
                "status": "error",
                "error": str(e),
            }
        ), 500

@ai_assistant_bp.route("/conversations/<conversation_id>", methods=["GET"])
def get_conversation(conversation_id: str):
    """
    Get conversation history by ID (for debugging/monitoring).

    Args:
        conversation_id: ID of the conversation

    Returns:
        JSON with conversation messages
    """
    try:
        conversation = get_or_create_conversation(conversation_id)
        messages = conversation.get_messages()
        
        return jsonify(
            {
                "success": True,
                "conversation_id": conversation_id,
                "message_count": len(messages),
                "messages": messages,
            }
        ), 200

    except Exception as e:
        logger.error(f"Get conversation error: {e}", exc_info=True)
        return jsonify(
            {
                "success": False,
                "error": str(e),
            }
        ), 500


@ai_assistant_bp.route("/conversations", methods=["GET"])
def list_conversations():
    """
    List all active conversations (for debugging/monitoring).

    Returns:
        JSON with list of all active conversations
    """
    try:
        from superset.ai_assistant.conversation import ConversationHistory
        
        conversations = ConversationHistory.get_all_conversations()
        
        return jsonify(
            {
                "success": True,
                "total": len(conversations),
                "conversations": conversations,
            }
        ), 200

    except Exception as e:
        logger.error(f"List conversations error: {e}", exc_info=True)
        return jsonify(
            {
                "success": False,
                "error": str(e),
            }
        ), 500