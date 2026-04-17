"""FastRecce — Location Acquisition OS."""

# Force ProactorEventLoop on Windows BEFORE any asyncio loop is created.
# uvicorn's default loop setup on Windows is SelectorEventLoop, which can't
# spawn subprocesses — breaking Playwright (Chromium launch). This runs at
# the earliest possible import time (root package), before anything in
# `app.api.main` or deeper modules wires up the event loop.
import asyncio as _asyncio
import sys as _sys

if _sys.platform == "win32":
    _asyncio.set_event_loop_policy(_asyncio.WindowsProactorEventLoopPolicy())

__version__ = "0.1.0"
