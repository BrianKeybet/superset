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
import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from superset.ai_assistant.tools import sales_target as st
from superset.utils import json

# Every date is relative to the run date. The latest data date is the first of
# the current month, so the current month is partial and the target is the
# next one.
LATEST = date.today().replace(day=1)
CURRENT = (LATEST.year, LATEST.month)
TARGET = st.shift_month(CURRENT, 1)


def _m(offset: int) -> st.Month:
    """The month ``offset`` months from the current one."""
    return st.shift_month(CURRENT, offset)


def _label(offset: int) -> str:
    return st.month_label(_m(offset))


def _monthly() -> dict[st.Month, dict[str, Any]]:
    """Target-month uplift +20% two years back and +10% one year back; the
    baseline (last three completed months) grows 10% year on year."""
    values = {
        _m(-27): 10,
        _m(-26): 10,
        _m(-25): 10,
        _m(-23): 12,  # target month, 2 years earlier
        _m(-15): 20,
        _m(-14): 20,
        _m(-13): 20,
        _m(-11): 22,  # target month, 1 year earlier
        _m(-3): 22,
        _m(-2): 22,
        _m(-1): 22,
        _m(0): 5,  # partial month
    }
    return {m: {"net_sales": v} for m, v in values.items()}


def _settings(**overrides: Any) -> dict[str, Any]:
    settings, _ = st.resolve_settings({}, 22, overrides)
    return settings


def _calculate(
    monthly: dict[st.Month, dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
    target: st.Month = TARGET,
    today: date = LATEST,
) -> dict[str, Any]:
    return st.calculate_target(
        _monthly() if monthly is None else monthly,
        ["net_sales"],
        LATEST,
        target,
        settings or _settings(),
        today=today,
    )


def test_month_helpers() -> None:
    year, month = CURRENT
    assert st.shift_month(CURRENT, 12) == (year + 1, month)
    assert st.shift_month(st.shift_month(CURRENT, 17), -17) == CURRENT
    assert st.last_complete_month(LATEST) == _m(-1)
    last_day = LATEST.replace(day=calendar.monthrange(year, month)[1])
    assert st.last_complete_month(last_day) == CURRENT
    assert st.parse_month(st.month_label(CURRENT)) == CURRENT
    epoch_ms = datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000
    assert st.parse_date(int(epoch_ms)) == LATEST
    assert st.parse_date(f"{LATEST.isoformat()}T00:00:00") == LATEST
    with pytest.raises(st.SalesTargetError):
        st.parse_month("next month")


def test_default_rule_worked_by_hand() -> None:
    result = _calculate()
    net = result["results"]["net_sales"]

    assert result["target_month"] == st.month_label(TARGET)
    assert result["baseline_months"] == [_label(-3), _label(-2), _label(-1)]
    assert net["baseline_average"] == 22
    assert net["yoy_growth_pct"] == 10.0
    assert [u["uplift_pct"] for u in net["uplift_by_year"]] == [10.0, 20.0]
    # (2 x 10% + 1 x 20%) / 3 = 13.33%
    assert net["seasonal_uplift_pct"] == 13.3
    assert net["seasonal_estimate"] == 24.93  # 22 x 1.1333
    assert net["last_year_estimate"] == 24.2  # 22 x 1.10
    assert net["expected"] == 24.57  # (24.933 + 24.2) / 2
    assert net["target"] == 25.8  # x 1.05
    assert net["method"].startswith("expected = 50% x seasonal (22.00 x (1 + 13.3%))")
    assert (
        f"Data runs to {LATEST.isoformat()}; {_label(0)} is partial and excluded."
        in result["caveats"]
    )
    assert "Seasonality rests on 2 years of history." in result["caveats"]


def test_partial_month_is_never_used() -> None:
    monthly = _monthly()
    monthly[_m(0)] = {"net_sales": 999}
    assert _calculate()["results"] == _calculate(monthly)["results"]


def test_inputs_list_the_months_used() -> None:
    roles = {row["month"]: row["role"] for row in _calculate()["inputs"]}
    assert roles[_label(-1)] == "baseline"
    assert roles[_label(-11)] == "target month, 1 year earlier"
    assert roles[_label(-27)] == "baseline, 2 years earlier"
    assert _label(0) not in roles


def test_overrides_change_the_result() -> None:
    settings = _settings(seasonal_weight=1.0, stretch_pct=0, uplift_year_weights=[1])
    net = _calculate(settings=settings)["results"]["net_sales"]
    # Equal year weights: (10% + 20%) / 2 = 15%; seasonal only; no stretch.
    assert net["expected"] == net["target"] == 25.3


def test_missing_last_year_uses_seasonal_only() -> None:
    monthly = _monthly()
    del monthly[_m(-11)]
    result = _calculate(monthly)
    net = result["results"]["net_sales"]
    assert net["last_year_estimate"] is None
    assert net["weights_used"] == {"seasonal": 1.0, "last_year": 0}
    assert net["expected"] == net["seasonal_estimate"]
    assert any("last-year estimate is left out" in c for c in result["caveats"])


def test_wide_uplift_spread_and_stale_data_are_flagged() -> None:
    monthly = _monthly()
    monthly[_m(-23)] = {"net_sales": 15}  # +50% two years back vs +10%
    result = _calculate(monthly, today=LATEST + timedelta(days=8))
    assert any("differ widely" in c for c in result["caveats"])
    assert any("8 days old" in c for c in result["caveats"])


def test_complete_target_month_is_rejected() -> None:
    with pytest.raises(st.SalesTargetError, match="already has complete data"):
        _calculate(target=_m(-1))


def test_missing_baseline_month_is_an_error() -> None:
    monthly = _monthly()
    del monthly[_m(-2)]
    with pytest.raises(st.SalesTargetError, match="baseline month"):
        _calculate(monthly)


def test_settings_merge_config_dataset_and_overrides() -> None:
    config = {"stretch_pct": 4, "datasets": {"22": {"baseline_months": 6}}}
    settings, applied = st.resolve_settings(config, 22, {"seasonal_weight": 0.7})
    assert settings["stretch_pct"] == 4
    assert settings["baseline_months"] == 6
    assert settings["seasonal_weight"] == 0.7
    assert applied == {"seasonal_weight": 0.7}
    assert "datasets" not in settings


@pytest.mark.parametrize(
    "override",
    [
        {"seasonal_weight": 1.5},
        {"baseline_months": 0},
        {"stretch_pct": 500},
        {"uplift_year_weights": [0, 0]},
    ],
)
def test_invalid_settings_are_rejected(override: dict[str, Any]) -> None:
    with pytest.raises(st.SalesTargetError):
        st.resolve_settings({}, 22, override)


def test_tool_queries_through_query_dataset(mocker: Any) -> None:
    rows = [
        {"YEAR": y, "MO": f"{m:02d}", "net_sales": v["net_sales"]}
        for (y, m), v in _monthly().items()
    ]
    calls: list[dict[str, Any]] = []

    def fake_query(request: dict[str, Any]) -> dict[str, Any]:
        calls.append(request)
        if request["columns"] == ["INVOICE_DATE"]:
            return {"data": [{"INVOICE_DATE": LATEST.isoformat(), "net_sales": 1}]}
        return {"data": rows}

    mocker.patch.object(st, "_query_dataset", side_effect=fake_query)
    mocker.patch.object(st, "_app_config", return_value={})

    payload = json.loads(
        st.run_sales_target(
            dataset_id=22,
            metrics=["net_sales"],
            filters=[{"col": "REGION", "op": "==", "val": "RIFTVALLEY"}],
            target_month=st.month_label(TARGET),
        )
    )

    assert payload["results"]["net_sales"]["target"] == 25.8
    assert payload["filters"] == [{"col": "REGION", "op": "==", "val": "RIFTVALLEY"}]
    assert payload["overrides"] == {}
    # The monthly query carries the filters; the latest-date query doesn't.
    assert calls[1]["filters"] == payload["filters"]
    assert "filters" not in calls[0]


def test_tool_returns_errors_as_json(mocker: Any) -> None:
    mocker.patch.object(
        st, "_query_dataset", side_effect=st.SalesTargetError("metric not found")
    )
    mocker.patch.object(st, "_app_config", return_value={})
    payload = json.loads(st.run_sales_target(dataset_id=22, metrics=["nope"]))
    assert payload == {"error": "metric not found"}


def test_tool_schema_is_exposed() -> None:
    tool = st.build_sales_target_tool()
    assert tool.name == "sales_target"
    assert "dataset_id" in tool.args
