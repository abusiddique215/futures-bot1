"""Smoke check on project_x_py 3.5.9 API surface.

If this test fails after a dependency bump, the TopstepX adapter likely
needs adjustment. These are pure introspection checks — no network.

Spec 02 §3.3 + Plan 8 T1.

Divergence notes from spec text (recorded here so future maintainers
don't waste time chasing them):
- module name is `project_x_py`, not `project_x`.
- Suite factory is `TradingSuite.create(...)` (classmethod), not
  `client.create_suite(...)` as the spec example showed.
- `OrderManager.place_order` uses snake_case `custom_tag` / `contract_id`
  (not camelCase `customTag` / `contractId`). The on-wire body that hits
  TopstepX is still camelCase, but the SDK call surface is Pythonic.
- `OrderSide.BUY == 0`, `OrderSide.SELL == 1` — matches our load-bearing
  encoding from spec §3.4.
"""
from __future__ import annotations


def test_project_x_py_module_name_is_underscored() -> None:
    """The package is `project-x-py` on PyPI; the importable module is
    `project_x_py` (single substitution, no nested dashes)."""
    import project_x_py

    assert project_x_py.__version__.startswith("3.5.")


def test_order_side_enum_matches_topstepx_wire_encoding() -> None:
    """OrderSide.BUY MUST be 0; OrderSide.SELL MUST be 1.

    This is the same load-bearing inversion documented in spec §3.4. If
    a future SDK upgrade flips these, the TopstepX adapter's defensive
    constants become wrong silently — and that's a real-money footgun.
    """
    from project_x_py import OrderSide

    assert int(OrderSide.BUY) == 0
    assert int(OrderSide.SELL) == 1


def test_order_type_market_is_two() -> None:
    """MARKET=2 per spec §3.3 ("type mapping"). MUST hold."""
    from project_x_py import OrderType

    assert int(OrderType.MARKET) == 2
    assert int(OrderType.LIMIT) == 1
    assert int(OrderType.STOP) == 4


def test_trading_suite_create_is_the_factory() -> None:
    """v3 renamed `client.create_suite` → `TradingSuite.create` (classmethod)."""
    from project_x_py import TradingSuite

    assert callable(TradingSuite.create)


def test_order_place_response_has_error_code_field() -> None:
    """Server rejections come back as `errorCode != 0`. We rely on the
    dataclass exposing that field (spec §3.3 server-side rule enforcement)."""
    from dataclasses import fields

    from project_x_py import OrderPlaceResponse

    field_names = {f.name for f in fields(OrderPlaceResponse)}
    assert {"orderId", "success", "errorCode", "errorMessage"} <= field_names
