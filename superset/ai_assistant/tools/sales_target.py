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
"""Fixed rule for monthly sales targets, exposed to the agent as a tool.

The model used to work targets out itself, which gave a different method,
different arithmetic and unstated judgement cuts on every run. This tool
applies one rule and returns every input and step, so the model only reports.

Rule (each number is a setting, see ``DEFAULT_SETTINGS``):

- Completed months only. The month holding the latest data date is partial,
  unless that date is the month's last day.
- Baseline: the average of the last ``baseline_months`` completed months
  before the target month.
- Seasonal estimate: baseline x (1 + uplift). A year's uplift is the target
  month's value over the same baseline months that year; years are averaged
  with ``uplift_year_weights`` (most recent first).
- Last-year estimate: the target month a year earlier x (1 + year-on-year
  growth), where growth compares the baseline with the same months a year
  earlier.
- Expected = ``seasonal_weight`` x seasonal + (1 - weight) x last-year.
- Target = expected x (1 + ``stretch_pct`` / 100).

Settings come from ``AI_SALES_TARGET`` in superset_config.py (a restart
applies them, no rebuild), optionally per dataset, and the model may pass
per-question overrides when the user asks for them.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timezone
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from superset.utils import json

logger = logging.getLogger(__name__)

TOOL_NAME = "sales_target"

DEFAULT_SETTINGS: dict[str, Any] = {
    "baseline_months": 3,
    "seasonal_weight": 0.5,
    "uplift_year_weights": [2, 1],
    "stretch_pct": 5.0,
    # Columns holding the invoice year, month ('01'-'12') and date.
    "year_column": "YEAR",
    "month_column": "MO",
    "date_column": "INVOICE_DATE",
    # Per-dataset settings, keyed by dataset id, e.g. {22: {"stretch_pct": 4}}.
    "datasets": {},
}

_OVERRIDE_KEYS = (
    "baseline_months",
    "seasonal_weight",
    "uplift_year_weights",
    "stretch_pct",
)

# Uplifts further apart than this (percentage points) get a caveat.
_UPLIFT_SPREAD_CAVEAT_PTS = 10.0
# Latest data older than this many days gets a staleness caveat.
_STALE_DATA_DAYS = 3

Month = tuple[int, int]


class SalesTargetError(ValueError):
    """A target can't be calculated; the message is shown to the model."""


class SalesTargetFilter(BaseModel):
    col: str = Field(..., description="Column name")
    op: str = Field("==", description='Operator, e.g. "==", "IN", "!="')
    val: Any = Field(None, description="Value, or a list for IN / NOT IN")


class SalesTargetRequest(BaseModel):
    dataset_id: int = Field(..., description="Dataset id")
    metrics: list[str] = Field(
        ...,
        min_length=1,
        max_length=4,
        description='Saved metric names, e.g. ["net_sales", "tonnes"]',
    )
    filters: list[SalesTargetFilter] = Field(
        default_factory=list,
        description='Same format as query_dataset, e.g. [{"col": "REGION", '
        '"op": "==", "val": "RIFTVALLEY"}]',
    )
    target_month: str | None = Field(
        None, description="YYYY-MM. Defaults to next calendar month."
    )
    baseline_months: int | None = Field(
        None, description="Override: number of completed months in the baseline"
    )
    seasonal_weight: float | None = Field(
        None,
        description="Override: weight (0-1) of the seasonal estimate; the "
        "last-year estimate gets the rest",
    )
    uplift_year_weights: list[float] | None = Field(
        None, description="Override: weights of each year's uplift, most recent first"
    )
    stretch_pct: float | None = Field(
        None, description="Override: target = expected x (1 + stretch_pct / 100)"
    )


TOOL_DESCRIPTION = (
    "Calculate the expected outcome and recommended target for a future month "
    "with the company's fixed rule. Use it for every monthly sales target or "
    "forecast instead of computing one yourself. Give the dataset, saved metric "
    "names and filters (query_dataset format). It uses completed months only "
    "and returns the inputs, each step, the method, the settings and caveats. "
    "Report its figures as returned: do not recompute, re-weight or adjust "
    "them. Pass baseline_months, seasonal_weight, uplift_year_weights or "
    "stretch_pct only when the user asks for different settings."
)


# --------------------------------------------------------------------------
# Months and dates
# --------------------------------------------------------------------------


def shift_month(month: Month, offset: int) -> Month:
    """Return ``month`` moved by ``offset`` months."""
    index = month[0] * 12 + month[1] - 1 + offset
    return index // 12, index % 12 + 1


def month_label(month: Month) -> str:
    return f"{month[0]:04d}-{month[1]:02d}"


def parse_month(text: str) -> Month:
    """Parse "YYYY-MM"."""
    try:
        year, mon = (int(part) for part in str(text).strip()[:7].split("-"))
    except ValueError as exc:
        raise SalesTargetError(f'target_month must be "YYYY-MM", got {text!r}') from exc
    if not 1 <= mon <= 12:
        raise SalesTargetError(f'target_month must be "YYYY-MM", got {text!r}')
    return year, mon


def parse_date(value: Any) -> date:
    """Parse a date returned by a query: ISO text, datetime or epoch millis."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise SalesTargetError(f"Could not read the latest date {value!r}") from exc


def last_complete_month(latest: date) -> Month:
    """The last month whose data is complete, given the latest data date."""
    month = (latest.year, latest.month)
    if latest.day == calendar.monthrange(latest.year, latest.month)[1]:
        return month
    return shift_month(month, -1)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


def resolve_settings(
    config: dict[str, Any] | None,
    dataset_id: int,
    overrides: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge defaults, config, per-dataset config and per-question overrides.

    Returns (settings, the overrides actually applied).
    """
    settings = {**DEFAULT_SETTINGS, **(config or {})}
    per_dataset = settings.get("datasets") or {}
    dataset_settings = per_dataset.get(dataset_id) or per_dataset.get(str(dataset_id))
    settings.update(dataset_settings or {})
    settings.pop("datasets", None)
    applied = {
        k: v for k, v in overrides.items() if k in _OVERRIDE_KEYS and v is not None
    }
    settings.update(applied)
    _validate_settings(settings)
    return settings, applied


def _validate_settings(settings: dict[str, Any]) -> None:
    if not 1 <= int(settings["baseline_months"]) <= 12:
        raise SalesTargetError("baseline_months must be between 1 and 12")
    if not 0 <= float(settings["seasonal_weight"]) <= 1:
        raise SalesTargetError("seasonal_weight must be between 0 and 1")
    if not -50 <= float(settings["stretch_pct"]) <= 100:
        raise SalesTargetError("stretch_pct must be between -50 and 100")
    weights = settings["uplift_year_weights"]
    if not weights or any(w < 0 for w in weights) or sum(weights) <= 0:
        raise SalesTargetError(
            "uplift_year_weights must be non-negative and not all zero"
        )


# --------------------------------------------------------------------------
# Calculation (pure)
# --------------------------------------------------------------------------


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 1)


def _year_weight(weights: list[float], index: int) -> float:
    return float(weights[index] if index < len(weights) else weights[-1])


class _Series:
    """Monthly values of one metric, restricted to completed months."""

    def __init__(
        self,
        monthly: dict[Month, dict[str, Any]],
        metric: str,
        last_complete: Month,
    ) -> None:
        self.values: dict[Month, float] = {}
        for month, row in monthly.items():
            value = row.get(metric)
            if month <= last_complete and value is not None:
                self.values[month] = float(value)

    def get(self, month: Month) -> float | None:
        return self.values.get(month)

    def average(self, months: list[Month]) -> float | None:
        values = [self.values.get(m) for m in months]
        if any(v is None for v in values):
            return None
        return sum(values) / len(values)  # type: ignore[arg-type]

    def earliest(self) -> Month | None:
        return min(self.values) if self.values else None


def _uplifts(
    series: _Series, target: Month, baseline: list[Month]
) -> list[dict[str, Any]]:
    """Each earlier year's uplift of the target month over the same baseline."""
    uplifts: list[dict[str, Any]] = []
    earliest = series.earliest()
    years_back = 1
    while earliest is not None and shift_month(target, -12 * years_back) >= earliest:
        month = shift_month(target, -12 * years_back)
        value = series.get(month)
        reference = series.average([shift_month(m, -12 * years_back) for m in baseline])
        if value is not None and reference:
            uplifts.append(
                {
                    "year": month[0],
                    "years_back": years_back,
                    "target_month_value": value,
                    "baseline_average": reference,
                    "uplift": value / reference - 1,
                }
            )
        years_back += 1
    return uplifts


def _calculate_metric(  # noqa: C901
    series: _Series,
    metric: str,
    target: Month,
    baseline: list[Month],
    settings: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Run the rule for one metric. Returns (result, notes)."""
    notes: list[str] = []
    base = series.average(baseline)
    if base is None:
        raise SalesTargetError(
            f"{metric}: no complete data for every baseline month "
            f"({', '.join(month_label(m) for m in baseline)})"
        )

    prior = series.average([shift_month(m, -12) for m in baseline])
    yoy = base / prior - 1 if prior else None

    uplifts = _uplifts(series, target, baseline)
    weights = settings["uplift_year_weights"]
    seasonal = uplift = None
    if uplifts:
        year_weights = [_year_weight(weights, i) for i in range(len(uplifts))]
        uplift = sum(
            w * u["uplift"] for w, u in zip(year_weights, uplifts, strict=True)
        ) / sum(year_weights)
        seasonal = base * (1 + uplift)
    else:
        notes.append(
            f"{metric}: no earlier {month_label(target)[5:]} to measure "
            "seasonality, so the seasonal estimate is left out"
        )

    last_year = series.get(shift_month(target, -12))
    same_month = (
        last_year * (1 + yoy) if last_year is not None and yoy is not None else None
    )
    if same_month is None:
        notes.append(
            f"{metric}: no same month last year with year-on-year growth, "
            "so the last-year estimate is left out"
        )

    seasonal_weight = float(settings["seasonal_weight"])
    parts = [
        (seasonal, seasonal_weight),
        (same_month, 1 - seasonal_weight),
    ]
    available = [(v, w) for v, w in parts if v is not None and w > 0]
    if available:
        total = sum(w for _, w in available)
        expected = sum(v * w for v, w in available) / total
        used_weights = {
            "seasonal": round(seasonal_weight / total, 3)
            if seasonal is not None
            else 0,
            "last_year": round((1 - seasonal_weight) / total, 3)
            if same_month is not None
            else 0,
        }
    elif seasonal is not None or same_month is not None:
        expected = seasonal if seasonal is not None else same_month
        used_weights = {
            "seasonal": 1.0 if seasonal is not None else 0,
            "last_year": 1.0 if seasonal is None else 0,
        }
    else:
        expected = base
        used_weights = {"seasonal": 0, "last_year": 0}
        notes.append(f"{metric}: no history for either estimate; expected = baseline")

    stretch = float(settings["stretch_pct"]) / 100
    target_value = expected * (1 + stretch)

    method = (
        f"expected = {used_weights['seasonal']:.0%} x seasonal "
        f"({_fmt(base)} x (1 {_signed_pct(uplift)})) = {_fmt(seasonal)}"
        f" + {used_weights['last_year']:.0%} x last year "
        f"({_fmt(last_year)} x (1 {_signed_pct(yoy)})) = {_fmt(same_month)}"
        f" -> {_fmt(expected)}; target = expected x (1 + {stretch:.0%})"
        f" = {_fmt(target_value)}"
    )

    result = {
        "expected": _round(expected),
        "target": _round(target_value),
        "baseline_average": _round(base),
        "baseline_average_year_earlier": _round(prior),
        "yoy_growth_pct": _pct(yoy),
        "seasonal_uplift_pct": _pct(uplift),
        "uplift_by_year": [
            {
                "year": u["year"],
                "target_month_value": _round(u["target_month_value"]),
                "baseline_average": _round(u["baseline_average"]),
                "uplift_pct": _pct(u["uplift"]),
                "weight": _year_weight(weights, i),
            }
            for i, u in enumerate(uplifts)
        ],
        "seasonal_estimate": _round(seasonal),
        "same_month_last_year": _round(last_year),
        "last_year_estimate": _round(same_month),
        "weights_used": used_weights,
        "method": method,
    }
    return result, notes


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.2f}"


def _signed_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{'+' if value >= 0 else '-'} {abs(value):.1%}"


def _input_rows(
    monthly: dict[Month, dict[str, Any]],
    metrics: list[str],
    target: Month,
    baseline: list[Month],
    years_back: int,
) -> list[dict[str, Any]]:
    """The monthly figures the calculation used, newest first."""
    roles: dict[Month, str] = {}
    for back in range(years_back, 0, -1):
        suffix = f", {back} year{'s' if back > 1 else ''} earlier"
        roles[shift_month(target, -12 * back)] = f"target month{suffix}"
        for month in baseline:
            roles[shift_month(month, -12 * back)] = f"baseline{suffix}"
    for month in baseline:
        roles[month] = "baseline"
    rows = []
    for month in sorted(roles, reverse=True):
        row: dict[str, Any] = {"month": month_label(month), "role": roles[month]}
        for metric in metrics:
            value = monthly.get(month, {}).get(metric)
            row[metric] = _round(float(value)) if value is not None else None
        rows.append(row)
    return rows


def calculate_target(
    monthly: dict[Month, dict[str, Any]],
    metrics: list[str],
    latest: date,
    target: Month,
    settings: dict[str, Any],
    today: date | None = None,
) -> dict[str, Any]:
    """Apply the rule to monthly totals. Pure: no queries, no config."""
    last_complete = last_complete_month(latest)
    if target <= last_complete:
        raise SalesTargetError(
            f"{month_label(target)} already has complete data (data runs to "
            f"{latest.isoformat()}); choose a later month"
        )
    count = int(settings["baseline_months"])
    end = min(last_complete, shift_month(target, -1))
    baseline = [shift_month(end, -i) for i in range(count - 1, -1, -1)]

    results: dict[str, Any] = {}
    caveats: list[str] = []
    years_back = 1
    for metric in metrics:
        series = _Series(monthly, metric, last_complete)
        result, notes = _calculate_metric(series, metric, target, baseline, settings)
        results[metric] = result
        caveats.extend(notes)
        years_back = max(years_back, len(result["uplift_by_year"]))

    partial = shift_month(last_complete, 1)
    if partial <= (latest.year, latest.month):
        caveats.append(
            f"Data runs to {latest.isoformat()}; {month_label(partial)} is partial "
            "and excluded."
        )
    first = results[metrics[0]]
    uplift_values = [u["uplift_pct"] for u in first["uplift_by_year"]]
    if uplift_values:
        caveats.append(
            f"Seasonality rests on {len(uplift_values)} year"
            f"{'s' if len(uplift_values) > 1 else ''} of history."
        )
        if max(uplift_values) - min(uplift_values) > _UPLIFT_SPREAD_CAVEAT_PTS:
            caveats.append(
                "The yearly uplifts differ widely ("
                + ", ".join(f"{v:+.1f}%" for v in uplift_values)
                + "), so treat the seasonal estimate as indicative."
            )
    today = today or date.today()
    if (today - latest).days > _STALE_DATA_DAYS:
        caveats.append(
            f"The latest data is {(today - latest).days} days old; the source "
            "may not be up to date."
        )

    return {
        "target_month": month_label(target),
        "latest_data_date": latest.isoformat(),
        "baseline_months": [month_label(m) for m in baseline],
        "results": results,
        "inputs": _input_rows(monthly, metrics, target, baseline, years_back),
        "caveats": caveats,
        "settings": {k: settings[k] for k in _OVERRIDE_KEYS},
        "instructions": (
            "Lead with expected and target per metric. Show the inputs, the "
            "method line(s) and the settings as returned; do not recompute or "
            "adjust these figures."
        ),
    }


# --------------------------------------------------------------------------
# Data access (through query_dataset, so permissions and RLS apply)
# --------------------------------------------------------------------------


def _query_dataset(request: dict[str, Any]) -> dict[str, Any]:
    from superset.ai_assistant.mcp_client import get_mcp_tools

    tools = get_mcp_tools(tool_filter=["query_dataset"])
    if not tools:
        raise SalesTargetError("The query_dataset tool is not available")
    # Call the wrapper directly (not .invoke) so this inner query doesn't show
    # up as a separate tool call in the agent's stream.
    func = getattr(tools[0], "func", None)
    if func is None:
        raise SalesTargetError("The query_dataset tool is not callable")
    text = func(request=request)
    if isinstance(text, str) and text.startswith("❌"):
        raise SalesTargetError(text.lstrip("❌ ").strip())
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise SalesTargetError(f"Unexpected query result: {str(text)[:200]}") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise SalesTargetError(str(payload["error"]))
    return payload


def fetch_monthly(
    dataset_id: int,
    metrics: list[str],
    filters: list[dict[str, Any]],
    settings: dict[str, Any],
) -> dict[Month, dict[str, Any]]:
    year_col, month_col = settings["year_column"], settings["month_column"]
    payload = _query_dataset(
        {
            "dataset_id": dataset_id,
            "metrics": metrics,
            "columns": [year_col, month_col],
            "filters": filters,
            "row_limit": 1000,
        }
    )
    monthly: dict[Month, dict[str, Any]] = {}
    for row in payload.get("data") or []:
        try:
            month = (int(row[year_col]), int(row[month_col]))
        except (KeyError, TypeError, ValueError):
            continue
        monthly[month] = {m: row.get(m) for m in metrics}
    if not monthly:
        raise SalesTargetError("No monthly data matched these filters")
    return monthly


def fetch_latest_date(dataset_id: int, metric: str, settings: dict[str, Any]) -> date:
    """Latest date in the whole dataset (not just the filtered slice), so a
    region with no sales on the last day doesn't shift the partial month."""
    date_col = settings["date_column"]
    payload = _query_dataset(
        {
            "dataset_id": dataset_id,
            "metrics": [metric],
            "columns": [date_col],
            "order_by": [date_col],
            "order_desc": True,
            "row_limit": 1,
        }
    )
    rows = payload.get("data") or []
    if not rows or rows[0].get(date_col) is None:
        raise SalesTargetError(f"Could not find the latest {date_col}")
    return parse_date(rows[0][date_col])


def _app_config() -> dict[str, Any]:
    try:
        from flask import current_app

        return dict(current_app.config.get("AI_SALES_TARGET") or {})
    except RuntimeError:  # no app context
        return {}


def run_sales_target(**kwargs: Any) -> str:
    """Tool entry point: returns JSON, with an "error" key on failure."""
    try:
        request = SalesTargetRequest(**kwargs)
        settings, overrides = resolve_settings(
            _app_config(),
            request.dataset_id,
            {k: getattr(request, k) for k in _OVERRIDE_KEYS},
        )
        filters = [f.model_dump() for f in request.filters]
        latest = fetch_latest_date(request.dataset_id, request.metrics[0], settings)
        monthly = fetch_monthly(request.dataset_id, request.metrics, filters, settings)
        today = date.today()
        target = (
            parse_month(request.target_month)
            if request.target_month
            else shift_month((today.year, today.month), 1)
        )
        result = calculate_target(
            monthly, request.metrics, latest, target, settings, today=today
        )
        result["dataset_id"] = request.dataset_id
        result["filters"] = filters
        result["overrides"] = overrides
        return json.dumps(result)
    except ValueError as exc:  # SalesTargetError and pydantic validation
        logger.info("sales_target could not calculate: %s", exc)
        return json.dumps({"error": str(exc)})


def build_sales_target_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=run_sales_target,
        name=TOOL_NAME,
        description=TOOL_DESCRIPTION,
        args_schema=SalesTargetRequest,
    )
