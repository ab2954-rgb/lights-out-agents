import pytest

from lights_out.checkpointing import make_checkpointer
from lights_out.ledger.evidence_ledger import verify_chain
from lights_out.tools import erp_tools


def test_memory_checkpointer_default(monkeypatch):
    monkeypatch.delenv("LIGHTS_OUT_PG_DSN", raising=False)
    with make_checkpointer() as cp:
        from langgraph.checkpoint.memory import MemorySaver
        assert isinstance(cp, MemorySaver)


def test_mcp_server_tools_and_ledger():
    pytest.importorskip("mcp")
    import asyncio

    from lights_out import mcp_server

    erp_tools.load_fixture(erp_tools.default_fixture())
    server = mcp_server.build_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"get_gl_lines", "get_bank_lines", "post_journal_entry", "ledger_export"} <= names
    res = asyncio.run(server.call_tool("post_journal_entry", {"je_id": "JE-MCP-1", "debit_account": "6150", "credit_account": "1010", "amount": 1.0, "memo": "t"}))
    assert "posted" in str(res)
    exported = asyncio.run(server.call_tool("ledger_export", {}))
    assert verify_chain(mcp_server.LEDGER.export()) == (True, None)
    assert exported
