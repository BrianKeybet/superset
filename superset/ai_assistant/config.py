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
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# LLM Provider Configuration
# -----------------------------------------------------------------------

# Default models. Keep these current — they are the documented defaults in
# docs/CLAUDE.md and are referenced by both get_llm_instance and get_llm_config.
DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"

# Cache LLM instances by resolved config so we don't reconstruct a client on
# every request. Keyed on the settings that actually change the client, not the
# API key (which we keep out of the cache key).
_llm_cache: dict[tuple[str, str, float, int, bool], Any] = {}


def get_llm_provider() -> Literal["openai", "anthropic"]:
    """Get configured LLM provider from environment."""
    provider = os.getenv("AI_LLM_PROVIDER", "openai").lower()
    if provider not in ("openai", "anthropic"):
        logger.warning("Invalid AI_LLM_PROVIDER '%s'. Defaulting to 'openai'", provider)
        return "openai"
    return provider  # type: ignore


def _resolve_llm_settings() -> tuple[str, str, float, int, bool]:
    """Resolve (provider, model, temperature, max_tokens, streaming) from env."""
    provider = get_llm_provider()
    temperature = float(os.getenv("AI_TEMPERATURE", "0.7"))
    max_tokens = int(os.getenv("AI_MAX_TOKENS", "4096"))
    streaming = os.getenv("AI_ENABLE_STREAMING", "true").lower() == "true"
    if provider == "openai":
        model = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    else:
        model = os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
    return provider, model, temperature, max_tokens, streaming


def get_llm_cache_key() -> tuple[str, str, float, int, bool]:
    """Return the config tuple identifying the current LLM instance.

    Used by the agent cache so it can rebuild only when the LLM config changes.
    """
    return _resolve_llm_settings()


def _build_llm(
    provider: str,
    model: str,
    temperature: float,
    max_tokens: int,
    streaming: bool,
) -> Any:
    """Construct a fresh LLM client for the given settings."""
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when AI_LLM_PROVIDER=openai")
        logger.info("🤖 Initializing OpenAI LLM: %s", model)
        return ChatOpenAI(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=streaming,
        )

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is required when AI_LLM_PROVIDER=anthropic")
    logger.info("🤖 Initializing Anthropic LLM: %s", model)
    anthropic_kwargs: dict[str, Any] = {
        "api_key": api_key,
        "model": model,
        "max_tokens": max_tokens,
        "streaming": streaming,
        # Disable extended thinking: on current Claude models the streamed
        # tool-calling loop can re-send thinking blocks without their content,
        # causing "thinking.thinking: Field required" 400s. A tool-first
        # assistant doesn't need it. Set AI_ENABLE_THINKING=true to opt back in.
        "thinking": {"type": "disabled"},
    }
    if os.getenv("AI_ENABLE_THINKING", "false").lower() == "true":
        anthropic_kwargs.pop("thinking")
    # Newer Claude models (Sonnet 5, Opus 4.x, …) reject the deprecated
    # `temperature` parameter with a 400. Only send it when explicitly opted in
    # via AI_SEND_TEMPERATURE=true (for older models that still accept it).
    if os.getenv("AI_SEND_TEMPERATURE", "false").lower() == "true":
        anthropic_kwargs["temperature"] = temperature
    return ChatAnthropic(**anthropic_kwargs)


def get_llm_instance() -> Any:
    """
    Return a cached LLM instance based on configured provider.

    Supports OpenAI (ChatOpenAI) and Anthropic (ChatAnthropic). Instances are
    cached by resolved config, so repeated calls reuse the same client rather
    than reconstructing it on every request.

    Raises:
        ValueError: If required API keys are not configured
    """
    key = get_llm_cache_key()
    if key not in _llm_cache:
        _llm_cache[key] = _build_llm(*key)
    return _llm_cache[key]


def get_llm_config() -> dict[str, Any]:
    """Get complete LLM configuration as dictionary."""
    return {
        "provider": get_llm_provider(),
        "openai_api_key": bool(os.getenv("OPENAI_API_KEY")),
        "openai_model": os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        "anthropic_api_key": bool(os.getenv("ANTHROPIC_API_KEY")),
        "anthropic_model": os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL),
        "temperature": float(os.getenv("AI_TEMPERATURE", "0.7")),
        "max_tokens": int(os.getenv("AI_MAX_TOKENS", "4096")),
        "streaming_enabled": os.getenv("AI_ENABLE_STREAMING", "true").lower() == "true",
    }
