from __future__ import annotations

from slack_sdk.web.async_client import AsyncWebClient

from sre_agent.config import get_settings

_SEVERITY_COLORS = {
    "critical": "#FF0000",
    "high": "#FF8C00",
    "medium": "#FFD700",
    "low": "#36A64F",
}

_SEVERITY_EMOJI = {
    "critical": ":red_circle:",
    "high": ":large_orange_circle:",
    "medium": ":large_yellow_circle:",
    "low": ":large_green_circle:",
}


def _slack_client() -> AsyncWebClient:
    return AsyncWebClient(token=get_settings().slack_bot_token)


async def post_incident_report(
    channel: str,
    alert_title: str,
    severity: str,
    root_cause: str,
    findings: list[dict],
    recommendations: list[str],
    alert_id: str,
    code_changes: list[str] | None = None,
) -> dict:
    """Post a formatted incident RCA report to a Slack channel using Block Kit.

    Args:
        channel: Slack channel name or ID, e.g. '#sre-incidents'.
        alert_title: Short alert title for the header.
        severity: Severity level: critical | high | medium | low.
        root_cause: Root cause hypothesis (1-2 sentences).
        findings: List of {source, summary, evidence} dicts from sub-agents.
        recommendations: Ordered list of actionable recommendation strings.
        alert_id: Alert identifier for traceability.
        code_changes: Optional list of commit SHAs or PR URLs linked to the issue.

    Returns:
        dict with 'ts' (message timestamp) and 'channel'.
    """
    sev = severity.lower()
    color = _SEVERITY_COLORS.get(sev, "#808080")
    emoji = _SEVERITY_EMOJI.get(sev, ":white_circle:")

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {severity.upper()} | {alert_title}",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Root Cause Hypothesis*\n{root_cause}",
            },
        },
    ]

    if findings:
        findings_text = "\n".join(
            f"• *{f.get('source', 'Unknown')}*: {f.get('summary', '')}"
            for f in findings[:6]
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Key Findings*\n{findings_text}"},
        })

    if recommendations:
        rec_text = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(recommendations[:8]))
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Recommendations*\n{rec_text}"},
        })

    if code_changes:
        changes_text = "\n".join(f"• {c}" for c in code_changes[:5])
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Linked Code Changes*\n{changes_text}"},
        })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"Alert ID: `{alert_id}` | SRE Agent"}],
    })

    client = _slack_client()
    resp = await client.chat_postMessage(
        channel=channel,
        text=f"{emoji} {severity.upper()} | {alert_title}",
        attachments=[{"color": color, "blocks": blocks}],
    )
    return {"ts": resp["ts"], "channel": resp["channel"]}


async def post_message(
    channel: str,
    text: str,
    thread_ts: str | None = None,
) -> dict:
    """Post a plain-text message or thread reply to Slack.

    Args:
        channel: Slack channel name or ID.
        text: Message text (supports mrkdwn).
        thread_ts: Optional thread timestamp to reply in an existing thread.

    Returns:
        dict with 'ts' and 'channel'.
    """
    client = _slack_client()
    kwargs: dict = {"channel": channel, "text": text}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    resp = await client.chat_postMessage(**kwargs)
    return {"ts": resp["ts"], "channel": resp["channel"]}
