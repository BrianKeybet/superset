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

"""
Unit tests for MCP dataset schema validation.
"""

import pytest

from superset.mcp_service.dataset.schemas import (
    DatasetFilter,
    GetDatasetInfoRequest,
    ListDatasetsRequest,
)


class TestRequestSchemaAliasChoices:
    """Test that LLM-friendly field name variants are accepted on the
    dataset MCP tool request schemas, so callers sending 'id'/'dataset_id'
    instead of 'identifier' (or 'columns' instead of 'select_columns')
    don't silently have the field dropped."""

    def test_get_dataset_info_identifier_id_alias(self) -> None:
        req = GetDatasetInfoRequest.model_validate({"id": 42})
        assert req.identifier == 42

    def test_get_dataset_info_identifier_dataset_id_alias(self) -> None:
        req = GetDatasetInfoRequest.model_validate({"dataset_id": 42})
        assert req.identifier == 42

    def test_get_dataset_info_identifier_still_works(self) -> None:
        req = GetDatasetInfoRequest.model_validate({"identifier": 42})
        assert req.identifier == 42

    def test_get_dataset_info_select_columns_columns_alias(self) -> None:
        req = GetDatasetInfoRequest.model_validate(
            {"id": 42, "columns": ["id", "table_name"]}
        )
        assert req.select_columns == ["id", "table_name"]

    def test_list_datasets_select_columns_columns_alias(self) -> None:
        req = ListDatasetsRequest.model_validate({"columns": ["id", "table_name"]})
        assert req.select_columns == ["id", "table_name"]

    def test_list_datasets_search_and_filters_conflict_validation(self) -> None:
        """search and filters are mutually exclusive on ListDatasetsRequest,
        inherited from PaginatedListRequest.validate_search_and_filters."""
        with pytest.raises(
            ValueError,
            match="Cannot use both 'search' and 'filters' parameters simultaneously",
        ):
            ListDatasetsRequest(
                search="sample",
                filters=[DatasetFilter(col="table_name", opr="sw", value="test")],
            )


class TestQueryDatasetFilterValue:
    """A comparison filter must carry its value; 'value' is accepted for 'val'
    so it is never silently dropped into an ``== NULL`` match."""

    def test_value_alias_is_accepted(self) -> None:
        from superset.mcp_service.dataset.schemas import QueryDatasetFilter

        flt = QueryDatasetFilter.model_validate(
            {"col": "REGION", "op": "==", "value": "RIFTVALLEY"}
        )
        assert flt.val == "RIFTVALLEY"

    def test_val_still_works(self) -> None:
        from superset.mcp_service.dataset.schemas import QueryDatasetFilter

        flt = QueryDatasetFilter(col="REGION", op="IN", val=["A", "B"])
        assert flt.val == ["A", "B"]

    def test_missing_value_for_comparison_is_rejected(self) -> None:
        from superset.mcp_service.dataset.schemas import QueryDatasetFilter

        with pytest.raises(ValueError, match='needs a value in "val"'):
            QueryDatasetFilter.model_validate({"col": "REGION", "op": "=="})

    @pytest.mark.parametrize("op", ["IS NULL", "IS NOT NULL", "IS TRUE", "IS FALSE"])
    def test_value_free_ops_need_no_value(self, op: str) -> None:
        from superset.mcp_service.dataset.schemas import QueryDatasetFilter

        assert (
            QueryDatasetFilter.model_validate({"col": "REGION", "op": op}).val is None
        )
