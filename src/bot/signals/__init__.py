"""bot.signals — external signal ingestion (Discord, webhooks, fixtures).

Lux Bot's distinguishing feature is that it doesn't compute its own entries:
trade ideas arrive from an external source. This package defines the
`SignalSource` Protocol, the `SignalEvent` payload, and the concrete
implementations (Discord-backed for production, fixture-backed for tests).

Safety: every emitted `SignalEvent` must be converted to an `OrderIntent`
and passed through `TopstepRiskGate.approve_or_deny` before reaching a
broker. Signals NEVER bypass the gate; the gate's `max_position` cap
applies regardless of what the signal claimed.
"""
