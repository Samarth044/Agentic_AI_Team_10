"""The run that is currently executing (set by the Gateway). Kept in its own
module so the audit log, memory and agents can all read it without imports
going in circles."""

from __future__ import annotations

import contextvars

current = contextvars.ContextVar("portal_run", default=None)


def run_id() -> str:
    r = current.get()
    return r.run_id if r else ""
