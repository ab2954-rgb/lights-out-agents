"""MCP-style typed tools exposing enterprise systems to agents.

In production these are thin adapters over SAP (OData/BAPI), Oracle Fusion, NetSuite
(SuiteTalk) and Workday, published through a Model Context Protocol server so any
agent runtime can discover and call them with typed schemas. Here they are backed
by an in-memory fixture so the graph runs deterministically in CI.

Every tool is:
  * typed (Pydantic input schema -> JSON schema for the model),
  * idempotent where it mutates (posting the same JE twice is a no-op),
  * side-effect logged (callers append to the Evidence Ledger).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field


@dataclass
class GLLine:
    id: str
    account: str
    amount: float
    ref: str
    memo: str = ""


@dataclass
class BankLine:
    id: str
    amount: float
    ref: str
    counterparty: str = ""


@dataclass
class ERPFixture:
    gl: list[GLLine] = field(default_factory=list)
    bank: list[BankLine] = field(default_factory=list)
    posted_journals: dict[str, dict] = field(default_factory=dict)


_FIXTURE = ERPFixture()


def load_fixture(fx: ERPFixture) -> None:
    global _FIXTURE
    _FIXTURE = fx


def default_fixture() -> ERPFixture:
    """A small, realistic bank-to-GL reconciliation set with several exception types."""
    gl = [
        GLLine("GL-1", "1010-Cash", 12_500.00, "INV-2001", "Customer receipt"),
        GLLine("GL-2", "1010-Cash", 8_400.00, "INV-2002", "Customer receipt"),
        GLLine("GL-3", "1010-Cash", -3_200.00, "PAY-7781", "Vendor payment"),
        GLLine("GL-4", "1010-Cash", 950.00, "INV-2003", "Customer receipt"),
        GLLine("GL-5", "1010-Cash", 47_000.00, "INV-2004", "Customer receipt"),
    ]
    bank = [
        BankLine("BK-1", 12_500.00, "INV-2001", "ACME"),
        BankLine("BK-2", 8_400.00, "INV 2002", "Globex"),         # ref formatting differs
        BankLine("BK-3", -3_200.00, "PAY-7781", "Initech"),
        BankLine("BK-4", 935.00, "INV-2003", "Umbrella"),           # short-paid by 15.00 (bank fee)
        BankLine("BK-6", -42.50, "FEE", "BANK"),                    # bank charge, no GL entry
        # GL-5 has no bank line: receipt in transit (high materiality)
    ]
    return ERPFixture(gl=gl, bank=bank)


# ----------------------------------------------------------------------------- tools
class LedgerQuery(BaseModel):
    account: str = Field(description="GL account code, e.g. '1010-Cash'")


@tool("get_gl_lines", args_schema=LedgerQuery)
def get_gl_lines(account: str) -> list[dict]:
    """Return open GL lines for an account (SAP FI / Oracle GL adapter)."""
    return [vars(line) for line in _FIXTURE.gl if line.account == account]


class BankQuery(BaseModel):
    account: str = Field(description="Bank account alias, e.g. 'MAIN-USD'")


@tool("get_bank_lines", args_schema=BankQuery)
def get_bank_lines(account: str) -> list[dict]:  # noqa: ARG001 - single fixture account
    """Return unreconciled bank statement lines (treasury / bank connectivity adapter)."""
    return [vars(b) for b in _FIXTURE.bank]


class JournalEntry(BaseModel):
    je_id: str = Field(description="Idempotency key for the journal")
    debit_account: str
    credit_account: str
    amount: float
    memo: str
    source_refs: list[str] = Field(default_factory=list)


@tool("post_journal_entry", args_schema=JournalEntry)
def post_journal_entry(
    je_id: str,
    debit_account: str,
    credit_account: str,
    amount: float,
    memo: str,
    source_refs: Optional[list[str]] = None,
) -> dict:
    """Post a balanced journal entry to the ERP. Idempotent on je_id."""
    if je_id in _FIXTURE.posted_journals:
        return {"status": "already_posted", "je_id": je_id}
    _FIXTURE.posted_journals[je_id] = {
        "debit_account": debit_account,
        "credit_account": credit_account,
        "amount": amount,
        "memo": memo,
        "source_refs": source_refs or [],
    }
    return {"status": "posted", "je_id": je_id}


TOOLS = [get_gl_lines, get_bank_lines, post_journal_entry]


def tool_schemas() -> list[dict]:
    """JSON schemas as an MCP server would advertise them (tools/list)."""
    return [{"name": t.name, "description": t.description, "input_schema": t.args_schema.model_json_schema()} for t in TOOLS]
