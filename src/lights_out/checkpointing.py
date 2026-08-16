"""Checkpointer factory: in-memory for tests/demos, Postgres for production.

    from lights_out.checkpointing import make_checkpointer
    cp = make_checkpointer()                       # MemorySaver
    cp = make_checkpointer("postgresql://...")     # langgraph-checkpoint-postgres (pip install -e ".[postgres]")

Human-in-the-loop interrupts survive process restarts only with a durable checkpointer, so
production graphs are compiled with the Postgres saver; the graph code does not change.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from langgraph.checkpoint.memory import MemorySaver


@contextmanager
def make_checkpointer(dsn: Optional[str] = None) -> Iterator[object]:
    dsn = dsn or os.getenv("LIGHTS_OUT_PG_DSN")
    if not dsn:
        yield MemorySaver()
        return
    from langgraph.checkpoint.postgres import PostgresSaver  # optional dependency

    with PostgresSaver.from_conn_string(dsn) as saver:
        saver.setup()
        yield saver
