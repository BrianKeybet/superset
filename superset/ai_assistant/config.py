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
"""AI Assistant LLM Configuration - Support for OpenAI and Anthropic."""

import logging
import os
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# LLM Provider Configuration
# -----------------------------------------------------------------------

def get_llm_provider() -> Literal["openai", "anthropic"]:
    """Get configured LLM provider from environment."""
    provider = os.getenv("AI_LLM_PROVIDER", "openai").lower()
    if provider not in ("openai", "anthropic"):
        logger.warning(
            f"Invalid AI_LLM_PROVIDER '{provider}'. Defaulting to 'openai'"
        )
        return "openai"
    return provider  # type: ignore


def get_llm_instance():
    """
    Create and return LLM instance based on configured provider.

    Supports:
    - OpenAI GPT-4
    - Anthropic Claude

    Returns:
        Configured ChatOpenAI or ChatAnthropic instance

    Raises:
        ValueError: If required API keys are not configured
    """
    provider = get_llm_provider()
    temperature = float(os.getenv("AI_TEMPERATURE", "0.7"))
    max_tokens = int(os.getenv("AI_MAX_TOKENS", "4096"))

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is required when AI_LLM_PROVIDER=openai"
            )

        model = os.getenv("OPENAI_MODEL", "gpt-4")
        logger.info(f"🤖 Initializing OpenAI LLM: {model}")

        return ChatOpenAI(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=os.getenv("AI_ENABLE_STREAMING", "true").lower() == "true",
        )

    elif provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required when AI_LLM_PROVIDER=anthropic"
            )

        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        logger.info(f"🤖 Initializing Anthropic LLM: {model}")

        return ChatAnthropic(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    raise ValueError(f"Unsupported LLM provider: {provider}")


def get_llm_config() -> dict:
    """Get complete LLM configuration as dictionary."""
    return {
        "provider": get_llm_provider(),
        "openai_api_key": bool(os.getenv("OPENAI_API_KEY")),
        "openai_model": os.getenv("OPENAI_MODEL", "gpt-4"),
        "anthropic_api_key": bool(os.getenv("ANTHROPIC_API_KEY")),
        "anthropic_model": os.getenv(
            "ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"
        ),
        "temperature": float(os.getenv("AI_TEMPERATURE", "0.7")),
        "max_tokens": int(os.getenv("AI_MAX_TOKENS", "4096")),
        "streaming_enabled": os.getenv("AI_ENABLE_STREAMING", "true").lower()
        == "true",
    }
