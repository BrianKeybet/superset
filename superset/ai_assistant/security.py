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
"""Access control for the AI Assistant endpoints.

Gating layers, evaluated in order:

1. **Feature flag** — the ``AI_ASSISTANT`` flag must be on, else the endpoints
   behave as if they don't exist (404).
2. **Authentication** — the request must come from a logged-in user (401).
3. **RBAC** — the user must hold one of ``AI_ASSISTANT_ALLOWED_ROLES`` (403).
   An empty allow-list means any authenticated user qualifies; ``Admin`` always
   qualifies.
"""

import logging
from functools import wraps
from typing import Any, Callable

from flask import current_app, g, jsonify

from superset.extensions import feature_flag_manager

logger = logging.getLogger(__name__)

FEATURE_FLAG = "AI_ASSISTANT"


def is_ai_assistant_enabled() -> bool:
    """Whether the AI Assistant feature flag is on."""
    return feature_flag_manager.is_feature_enabled(FEATURE_FLAG)


def _current_user() -> Any:
    """Return the current user or None if anonymous/unset."""
    user = getattr(g, "user", None)
    if user is None or getattr(user, "is_anonymous", True):
        return None
    return user


def user_can_use_ai_assistant() -> bool:
    """Whether the current user passes the RBAC role check."""
    user = _current_user()
    if user is None:
        return False
    allowed_roles = current_app.config.get("AI_ASSISTANT_ALLOWED_ROLES") or []
    if not allowed_roles:
        # No allow-list configured: any authenticated user may use it.
        return True
    role_names = {role.name for role in getattr(user, "roles", [])}
    if "Admin" in role_names:
        return True
    return bool(role_names.intersection(allowed_roles))


def require_ai_access(func: Callable[..., Any]) -> Callable[..., Any]:
    """Enforce feature-flag, authentication, and RBAC gating on a route."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not is_ai_assistant_enabled():
            return jsonify({"success": False, "error": "AI Assistant is disabled"}), 404
        if _current_user() is None:
            return (
                jsonify({"success": False, "error": "Authentication required"}),
                401,
            )
        if not user_can_use_ai_assistant():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "You do not have access to the AI Assistant",
                    }
                ),
                403,
            )
        return func(*args, **kwargs)

    return wrapper
