from __future__ import annotations

from google.adk.agents import Agent, RemoteA2AAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams

from sre_agent.config import get_settings
from sre_agent.tools.opensearch import find_symbol, get_file_chunks, search_code_chunks

MODEL = LiteLlm(model="anthropic/claude-sonnet-4-5-20251001")

CODE_INTELLIGENCE_INSTRUCTION = """
You are the SRE Code Intelligence Agent for a large bank's data platform.

You have access to:
1. **OpenSearch code index** — AST-chunked index of all platform source code.
   Each chunk has: repo, file_path, start_line, end_line, chunk_type, symbol_name, content.
2. **Bitbucket MCP** — source code repositories. Use to find recent commits, PRs,
   file contents, and diff for changed files.
3. **Code Analysis Agent (A2A)** — a specialised agent you can delegate to for deep
   code analysis tasks that require reasoning over large code contexts.

## When to run (triggered by orchestrator):
- A stack trace or specific class/function name is present in the alert
- `suspect_code_change: true` in the triage result
- Investigation findings mention a code-level error (NPE, ClassCastException, etc.)

## Investigation Steps

1. **Identify affected code**:
   - Extract class/function names from the stack trace or error message
   - Use `find_symbol(<name>, symbol_type="class|function|method")` to locate them
   - Use `search_code_chunks(<error_message_fragment>)` for broader semantic search

2. **Get full code context**:
   - Use `get_file_chunks(<file_path>, <repo>)` to retrieve the full file's indexed chunks
   - Use Bitbucket MCP to get the raw file content if needed

3. **Find recent code changes**:
   - Use Bitbucket MCP tools to search recent commits on affected files (last 48 hours)
   - Look for merged PRs touching these files
   - Note commit SHA, author, PR title, merge timestamp

4. **Deep analysis (if needed)**:
   - If the change is complex, delegate to the `code_analysis_agent` (A2A):
     Ask it: "Given this stack trace [X] and this code change [Y], could the change
     have introduced this error? What is the code path that triggers it?"

5. **Assess impact**:
   - Is this error triggered by the code change?
   - Which other jobs/services import or use this class?
   - Is this a schema change, interface change, or logic bug?

## Output Format
Return structured JSON:
{
  "code_root_cause_found": <true|false>,
  "affected_files": ["<repo>/<file_path>", ...],
  "related_symbols": [{"symbol_name": "...", "file_path": "...", "repo": "..."}],
  "recent_commits": [
    {"sha": "...", "author": "...", "message": "...", "timestamp": "...", "pr_url": "..."}
  ],
  "code_hypothesis": "<explanation of how the code change caused the issue, or null>",
  "affected_downstream": ["<other jobs/services that use these symbols>"],
  "findings": [{"source": "<OpenSearch|Bitbucket|CodeAgent>", "summary": "...", "evidence": "..."}]
}

IMPORTANT: READ-ONLY analysis. Do not suggest code fixes — only identify root cause.
"""


def _build_code_intelligence_agent() -> Agent:
    s = get_settings()
    bitbucket_toolset = MCPToolset(
        connection_params=SseServerParams(url=s.bitbucket_mcp_url),
        toolset_name="bitbucket",
    )
    code_analysis_agent = RemoteA2AAgent(
        name="code_analysis_agent",
        description=(
            "Specialised agent for deep code analysis: interprets stack traces against "
            "the codebase, identifies code paths that triggered an error, and assesses "
            "the impact of recent commits on platform jobs."
        ),
        agent_card_url=f"{s.code_agent_a2a_url}/.well-known/agent.json",
    )
    return Agent(
        name="code_intelligence_agent",
        model=MODEL,
        description=(
            "Investigates code-level root causes using the OpenSearch AST code index, "
            "Bitbucket MCP for recent commits/PRs, and a remote Code Analysis Agent "
            "via A2A for deep code reasoning."
        ),
        instruction=CODE_INTELLIGENCE_INSTRUCTION,
        tools=[
            search_code_chunks,
            find_symbol,
            get_file_chunks,
            bitbucket_toolset,
        ],
        sub_agents=[code_analysis_agent],
    )


code_intelligence_agent = _build_code_intelligence_agent()
