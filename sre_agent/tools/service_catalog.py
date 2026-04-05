from __future__ import annotations

from sre_agent.knowledge.service_catalog import list_services_by_namespace, lookup_service


async def get_service_info(service_name: str) -> dict:
    """Look up service metadata from the platform service catalog.

    Returns ownership, on-call, SLO targets, dashboards, and runbook links
    for a given service or job name. Use this to:
    - Identify which team owns the affected service
    - Find the correct Slack channel to escalate to
    - Include SLO context in the RCA report
    - Link to existing dashboards and runbooks

    Args:
        service_name: Service, job, or application name to look up.
            Supports partial matching: 'kafka-orders', 'flink-orders',
            'orders-api', 'etl-pipeline-v2', etc.

    Returns:
        dict with service metadata:
          - service_name, display_name
          - team: owning team name
          - slack_channel: escalation channel (e.g. '#data-platform-oncall')
          - oncall_schedule: PagerDuty/OpsGenie schedule name
          - slo_uptime_pct: target uptime SLO (e.g. 99.9)
          - slo_latency_p99_ms: P99 latency SLO in milliseconds
          - dashboard_url: primary monitoring dashboard
          - runbook_url: team runbook wiki link
          - repository: source code repository
          - eks_namespace: Kubernetes namespace
        Returns {"found": false, "service_name": ...} if not found.
    """
    result = await lookup_service(service_name)
    if result:
        return {**result, "found": True}
    return {"found": False, "service_name": service_name,
            "note": "Service not in catalog. Check with platform team."}


async def get_services_in_namespace(namespace: str) -> dict:
    """List all services registered in a given EKS namespace.

    Args:
        namespace: Kubernetes namespace, e.g. 'flink-prod', 'databricks', 'api-gateway'.

    Returns:
        dict with 'services' list and 'count'.
    """
    services = await list_services_by_namespace(namespace)
    return {"namespace": namespace, "services": services, "count": len(services)}
