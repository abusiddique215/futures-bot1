"""Market spec registry — single source of truth for per-market parameters.

Replaces the symbol-startswith branching scattered across `bot.constants`,
`bot.risk.*`, and `bot.data.*` with a typed lookup against `MARKETS`.
"""
from __future__ import annotations
