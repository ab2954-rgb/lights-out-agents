"""MCP server exposing the ERP tools to any MCP-capable agent runtime.

    python -m lights_out.mcp_server            # stdio transport (Claude Desktop, LangGraph MCP adapters, etc.)

Every tool call is appended to an in-process Evidence Ledger; `ledger_export` returns the chain so a
client can verify it independently with `lights_out.ledger.evidence_ledger.verify_chain`.
The tool schemas are the same Pydantic models used by the LangGraph graph, so a tool that passes the
in-process tests is guaranteed to advertise the same contract over MCP.
"""
from __future__ import annotations

from typing import Optional

from lights_out.ledger.evidence_ledger import EvidenceLedger
from lights_out.tools import erp_tools

try:  # optional dependency: `pip install -e ".[mcp]"` — supports MCP SDK 1.x (FastMCP) and 2.x (MCPServer)
    from mcp.server.mcpserver import MCPServer as FastMCP  # SDK >= 2.0
except ImportError:  # pragma: no cover
    try:
        from mcp.server.fastmcp import FastMCP  # SDK 1.x
    except ImportError:
        FastMCP = None

LEDGER = EvidenceLedger()
ACTOR = "mcp:erp-tools"


def build_server(name: str = "lights-out-erp"):
    if FastMCP is None:
        raise RuntimeError("Install the MCP SDK: pip install 'lights-out-agents[mcp]'")
    server = FastMCP(name)

    @server.tool()
    def get_gl_lines(account: str) -> list[dict]:
        """Return open GL lines for an account (SAP FI / Oracle GL adapter)."""
        out = erp_tools.get_gl_lines.invoke({"account": account})
        LEDGER.append(actor=ACTOR, action="get_gl_lines", subject=account, autonomy_level="A0", payload={"n": len(out)})
        return out

    @server.tool()
    def get_bank_lines(account: str) -> list[dict]:
        """Return unreconciled bank statement lines (treasury / bank connectivity adapter)."""
        out = erp_tools.get_bank_lines.invoke({"account": account})
        LEDGER.append(actor=ACTOR, action="get_bank_lines", subject=account, autonomy_level="A0", payload={"n": len(out)})
        return out

    @server.tool()
    def post_journal_entry(je_id: str, debit_account: str, credit_account: str, amount: float, memo: str,
                           source_refs: Optional[list[str]] = None) -> dict:
        """Post a balanced journal entry to the ERP. Idempotent on je_id."""
        res = erp_tools.post_journal_entry.invoke({"je_id": je_id, "debit_account": debit_account,
                                                   "credit_account": credit_account, "amount": amount,
                                                   "memo": memo, "source_refs": source_refs or []})
        LEDGER.append(actor=ACTOR, action="post_journal_entry", subject=je_id, autonomy_level="A1",
                      payload=res, controls=("SOX-R2R-05 journal approval",))
        return res

    @server.tool()
    def ledger_export() -> list[dict]:
        """Export the hash-chained evidence ledger for independent verification."""
        return LEDGER.export()

    return server


def main() -> None:  # pragma: no cover
    erp_tools.load_fixture(erp_tools.default_fixture())
    build_server().run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
