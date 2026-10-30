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
"""A user detached by an earlier in-process tool call is re-attached.

The AI Assistant runs several MCP tools in one request; each call has its own
scoped session, so the ``g.user`` merged into one call's session is detached
when the next call starts. Reading ``user.roles`` must still work.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask_appbuilder.security.sqla.models import Role, User
from sqlalchemy import create_engine, inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import DetachedInstanceError

from superset.mcp_service import auth


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite://")
    security_tables = [
        table for name, table in User.metadata.tables.items() if name.startswith("ab_")
    ]
    User.metadata.create_all(engine, tables=security_tables)
    yield engine
    engine.dispose()


def _detached_user(engine: Engine) -> User:
    """A user loaded in a session that has since closed (roles not loaded)."""
    with sessionmaker(bind=engine)() as setup:
        setup.add(
            User(
                first_name="Brian",
                last_name="K",
                username="brian",
                email="brian@example.com",
                active=True,
                roles=[Role(name="Alpha")],
            )
        )
        setup.commit()
    first_call = sessionmaker(bind=engine)()
    user = first_call.query(User).filter_by(username="brian").one()
    first_call.close()
    return user


def test_detached_user_cannot_lazy_load_roles(engine: Engine) -> None:
    user = _detached_user(engine)

    assert sa_inspect(user).detached
    with pytest.raises(DetachedInstanceError):
        _ = user.roles


def test_attach_if_detached_merges_into_current_session(
    engine: Engine, mocker: Any
) -> None:
    user = _detached_user(engine)
    current: Session = sessionmaker(bind=engine)()
    mocker.patch("superset.db.session", current)

    attached = auth._attach_if_detached(user)

    assert attached is not None
    assert not sa_inspect(attached).detached
    assert [role.name for role in attached.roles] == ["Alpha"]
    current.close()


def test_attach_if_detached_leaves_attached_user_alone(
    engine: Engine, mocker: Any
) -> None:
    current: Session = sessionmaker(bind=engine)()
    user = User(username="x", first_name="x", last_name="x", email="x@example.com")
    current.add(user)
    merge = mocker.patch.object(current, "merge")
    mocker.patch("superset.db.session", current)

    assert auth._attach_if_detached(user) is user
    merge.assert_not_called()
    current.close()


@pytest.mark.parametrize("user", [None, MagicMock(name="guest-or-mock")])
def test_attach_if_detached_passes_non_orm_users_through(user: Any) -> None:
    assert auth._attach_if_detached(user) is user


def test_resolve_user_survives_repeated_in_process_calls(
    engine: Engine, mocker: Any
) -> None:
    """Three tool calls in a row, each in a fresh session, all resolve roles."""
    user = _detached_user(engine)
    mocker.patch.object(auth, "get_user_from_request", side_effect=lambda: user)

    for _ in range(3):
        call_session: Session = sessionmaker(bind=engine)()
        mocker.patch("superset.db.session", call_session)

        resolved = auth._resolve_user_with_retry()

        assert resolved is not None
        assert [role.name for role in resolved.roles] == ["Alpha"]
        # What the fork's _setup_user_context leaves in g.user: a copy bound to
        # this call's session, detached once the call's session closes.
        user = resolved
        call_session.close()
