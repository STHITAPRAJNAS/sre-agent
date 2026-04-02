from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from functools import partial
from typing import Any

import boto3

from sre_agent.config import get_settings


def _cw_client() -> Any:
    s = get_settings()
    return boto3.client(
        "cloudwatch",
        region_name=s.aws_region,
        aws_access_key_id=s.aws_access_key_id or None,
        aws_secret_access_key=s.aws_secret_access_key or None,
    )


def _logs_client() -> Any:
    s = get_settings()
    return boto3.client(
        "logs",
        region_name=s.aws_region,
        aws_access_key_id=s.aws_access_key_id or None,
        aws_secret_access_key=s.aws_secret_access_key or None,
    )


async def describe_cloudwatch_alarms(
    alarm_name_prefix: str | None = None,
    state: str = "ALARM",
) -> dict:
    """List CloudWatch alarms in a given state.

    Args:
        alarm_name_prefix: Optional prefix filter on alarm names.
        state: Alarm state to filter on: ALARM | OK | INSUFFICIENT_DATA.

    Returns:
        dict with key 'alarms' — list of {name, state, reason, dimensions, namespace}.
    """
    loop = asyncio.get_event_loop()
    client = _cw_client()

    kwargs: dict[str, Any] = {"StateValue": state}
    if alarm_name_prefix:
        kwargs["AlarmNamePrefix"] = alarm_name_prefix

    result = await loop.run_in_executor(None, partial(client.describe_alarms, **kwargs))

    alarms = [
        {
            "name": a["AlarmName"],
            "state": a["StateValue"],
            "reason": a.get("StateReason", ""),
            "dimensions": a.get("Dimensions", []),
            "namespace": a.get("Namespace", ""),
            "metric_name": a.get("MetricName", ""),
        }
        for a in result.get("MetricAlarms", [])
    ]
    return {"alarms": alarms, "count": len(alarms)}


async def get_cloudwatch_metric_statistics(
    namespace: str,
    metric_name: str,
    dimensions: list[dict[str, str]],
    start_time: str,
    end_time: str,
    period: int = 300,
    stat: str = "Average",
) -> dict:
    """Get CloudWatch metric statistics (datapoints).

    Args:
        namespace: AWS metric namespace, e.g. 'AWS/EKS' or 'FlinkMetrics'.
        metric_name: Name of the metric, e.g. 'CPUUtilization'.
        dimensions: List of dimension dicts, e.g. [{"Name": "JobName", "Value": "orders"}].
        start_time: ISO8601 start time, e.g. '2024-01-15T14:00:00Z'.
        end_time: ISO8601 end time.
        period: Aggregation period in seconds (default 300 = 5 min).
        stat: Statistic: Average | Sum | Maximum | Minimum | SampleCount.

    Returns:
        dict with key 'datapoints' — list of {timestamp, value, unit}.
    """
    loop = asyncio.get_event_loop()
    client = _cw_client()

    fn = partial(
        client.get_metric_statistics,
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=start_time,
        EndTime=end_time,
        Period=period,
        Statistics=[stat],
    )
    result = await loop.run_in_executor(None, fn)

    datapoints = sorted(
        [
            {
                "timestamp": dp["Timestamp"].isoformat(),
                "value": dp.get(stat, dp.get("Average", 0)),
                "unit": dp.get("Unit", ""),
            }
            for dp in result.get("Datapoints", [])
        ],
        key=lambda x: x["timestamp"],
    )
    return {"metric": f"{namespace}/{metric_name}", "datapoints": datapoints}


async def run_cloudwatch_logs_insights(
    log_group_names: list[str],
    query_string: str,
    start_time: int,
    end_time: int,
    limit: int = 100,
) -> dict:
    """Run a CloudWatch Logs Insights query and wait for results.

    Args:
        log_group_names: List of log group names to query.
        query_string: CloudWatch Logs Insights query, e.g.
            "fields @timestamp, @message | filter @message like /ERROR/ | limit 50".
        start_time: Start time as Unix epoch seconds.
        end_time: End time as Unix epoch seconds.
        limit: Maximum result rows (injected into query if not present).

    Returns:
        dict with keys: results (list of field/value rows), statistics.
    """
    loop = asyncio.get_event_loop()
    client = _logs_client()

    if "limit" not in query_string.lower():
        query_string = f"{query_string.rstrip()} | limit {limit}"

    start_fn = partial(
        client.start_query,
        logGroupNames=log_group_names,
        startTime=start_time,
        endTime=end_time,
        queryString=query_string,
        limit=limit,
    )
    start_result = await loop.run_in_executor(None, start_fn)
    query_id = start_result["queryId"]

    # Poll until complete (max 60 seconds)
    for _ in range(30):
        get_fn = partial(client.get_query_results, queryId=query_id)
        result = await loop.run_in_executor(None, get_fn)
        status = result["status"]
        if status in ("Complete", "Failed", "Cancelled"):
            break
        await asyncio.sleep(2)

    rows = [
        {field["field"]: field["value"] for field in row}
        for row in result.get("results", [])
    ]
    return {
        "query_id": query_id,
        "status": result["status"],
        "results": rows,
        "statistics": result.get("statistics", {}),
    }
