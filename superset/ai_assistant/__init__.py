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
"""Superset AI Assistant module."""

from flask import Blueprint, current_app

ai_assistant_bp = Blueprint(
    "ai_assistant",
    __name__,
    url_prefix="/api/v1/ai",
    static_folder="static",
)

# Disable CSRF protection for AI Assistant API endpoints (authenticated via API)
ai_assistant_bp.config = {"session.cookie_csrf_enabled": False}


def disable_csrf_on_registration(app):
    """Disable CSRF for AI Assistant routes."""
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith("ai_assistant"):
            exempt_list = app.config.setdefault("WTF_CSRF_EXEMPT_LIST", [])
            if rule.endpoint not in exempt_list:
                exempt_list.append(rule.endpoint)


# Import routes to register them on the blueprint (MUST be after blueprint creation)
from superset.ai_assistant import api  # noqa: F401, E402
