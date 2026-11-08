"""S4: indexes on finished_at for ingestion metrics period filters.

The metrics page filters/counts runs and batches by finished_at window, so
both tables carry a dedicated btree index on that column.
"""

import pytest
from django.db import connection


def _indexed_column_lists(table: str) -> list[list[str]]:
    """Return the column list of every index defined on ``table``."""
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    return [
        constraint["columns"]
        for constraint in constraints.values()
        if constraint.get("index")
    ]


@pytest.mark.django_db
class TestFinishedAtIndexes:
    """Both finished_at columns are indexed."""

    @pytest.mark.parametrize(
        "table",
        ["ingestion_ingestionrun", "ingestion_censusexecutionbatch"],
    )
    def test_finished_at_has_single_column_index(self, table):
        assert ["finished_at"] in _indexed_column_lists(table)
