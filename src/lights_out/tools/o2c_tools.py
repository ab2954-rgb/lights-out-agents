"""Order-to-Cash tools: sales orders, credit, inventory, and order release — the second Lights-Out function.

Same contract as `erp_tools`: typed inputs (Pydantic -> JSON schema), idempotent mutations, in-memory
fixture so the graph runs deterministically in CI. Production analogue: SAP SD / Oracle OM adapters
behind an MCP server.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.tools import tool
from pydantic import BaseModel, Field


@dataclass
class SalesOrder:
    id: str
    customer: str
    sku: str
    qty: int
    unit_price: float
    currency: str = "USD"


@dataclass
class O2CFixture:
    orders: list[SalesOrder] = field(default_factory=list)
    credit_limit: dict[str, float] = field(default_factory=dict)      # customer -> remaining credit
    stock: dict[str, int] = field(default_factory=dict)               # sku -> on-hand
    price_list: dict[str, float] = field(default_factory=dict)        # sku -> list price
    released: dict[str, dict] = field(default_factory=dict)


_FX = O2CFixture()


def load_fixture(fx: O2CFixture) -> None:
    global _FX
    _FX = fx


def default_fixture() -> O2CFixture:
    return O2CFixture(
        orders=[
            SalesOrder("SO-1", "ACME", "SKU-A", 10, 100.0),          # clean
            SalesOrder("SO-2", "Globex", "SKU-B", 5, 250.0),         # price mismatch (list 240)
            SalesOrder("SO-3", "Initech", "SKU-A", 500, 100.0),      # over credit
            SalesOrder("SO-4", "Umbrella", "SKU-C", 3, 80.0),        # no stock
            SalesOrder("SO-5", "Hooli", "SKU-B", 2, 240.0),          # clean, low value
        ],
        credit_limit={"ACME": 5_000, "Globex": 10_000, "Initech": 20_000, "Umbrella": 1_000, "Hooli": 3_000},
        stock={"SKU-A": 100, "SKU-B": 50, "SKU-C": 0},
        price_list={"SKU-A": 100.0, "SKU-B": 240.0, "SKU-C": 80.0},
    )


class OrderQuery(BaseModel):
    status: str = Field(default="open", description="open | released")


@tool("get_open_orders", args_schema=OrderQuery)
def get_open_orders(status: str = "open") -> list[dict]:
    """Return sales orders awaiting release (SAP SD / Oracle OM adapter)."""
    return [vars(o) for o in _FX.orders if (o.id not in _FX.released) == (status == "open")]


class CustomerQuery(BaseModel):
    customer: str


@tool("get_credit_exposure", args_schema=CustomerQuery)
def get_credit_exposure(customer: str) -> dict:
    """Remaining credit for a customer (credit management adapter)."""
    return {"customer": customer, "remaining_credit": _FX.credit_limit.get(customer, 0.0)}


class SkuQuery(BaseModel):
    sku: str


@tool("get_stock_and_price", args_schema=SkuQuery)
def get_stock_and_price(sku: str) -> dict:
    """On-hand stock and list price for a SKU (inventory + pricing adapters)."""
    return {"sku": sku, "on_hand": _FX.stock.get(sku, 0), "list_price": _FX.price_list.get(sku)}


class Release(BaseModel):
    order_id: str = Field(description="Idempotency key")
    reason: str


@tool("release_order", args_schema=Release)
def release_order(order_id: str, reason: str) -> dict:
    """Release a sales order for fulfilment. Idempotent on order_id; decrements stock and credit."""
    if order_id in _FX.released:
        return {"status": "already_released", "order_id": order_id}
    o = next(x for x in _FX.orders if x.id == order_id)
    _FX.stock[o.sku] = _FX.stock.get(o.sku, 0) - o.qty
    _FX.credit_limit[o.customer] = _FX.credit_limit.get(o.customer, 0.0) - o.qty * o.unit_price
    _FX.released[order_id] = {"reason": reason, "value": o.qty * o.unit_price}
    return {"status": "released", "order_id": order_id}


TOOLS = [get_open_orders, get_credit_exposure, get_stock_and_price, release_order]
