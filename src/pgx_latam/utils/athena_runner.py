"""Athena query execution helper with polling and result pagination."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import boto3

from pgx_latam.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_athena import AthenaClient


_POLL_INTERVAL_SECONDS = 2
_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}


class AthenaQueryError(RuntimeError):
    """Raised when an Athena query fails or is cancelled."""


def run_query(
    sql: str,
    database: str,
    output_location: str | None = None,
    workgroup: str | None = None,
) -> str:
    """Submit an Athena query and block until it reaches a terminal state.

    Args:
        sql: The SQL statement to execute.
        database: Target Glue database name.
        output_location: S3 URI for query results. Defaults to workgroup default.
        workgroup: Athena workgroup name. Defaults to settings value.

    Returns:
        QueryExecutionId of the completed query.

    Raises:
        AthenaQueryError: If the query fails or is cancelled.
    """
    settings = get_settings()
    client: AthenaClient = boto3.client("athena", region_name=settings.aws_region)

    wg = workgroup or settings.pgx_athena_workgroup
    kwargs: dict[str, Any] = {
        "QueryString": sql,
        "QueryExecutionContext": {"Database": database},
        "WorkGroup": wg,
    }
    if output_location:
        kwargs["ResultConfiguration"] = {"OutputLocation": output_location}

    response = client.start_query_execution(**kwargs)
    execution_id: str = response["QueryExecutionId"]

    while True:
        status_response = client.get_query_execution(QueryExecutionId=execution_id)
        state = status_response["QueryExecution"]["Status"]["State"]

        if state in _TERMINAL_STATES:
            if state != "SUCCEEDED":
                reason = (
                    status_response["QueryExecution"]["Status"]
                    .get("StateChangeReason", "no reason provided")
                )
                raise AthenaQueryError(
                    f"Athena query {execution_id} ended with state {state}: {reason}\n"
                    f"SQL: {sql[:500]}"
                )
            return execution_id

        time.sleep(_POLL_INTERVAL_SECONDS)
