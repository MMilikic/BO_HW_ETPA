"""Builders for the tests of matching: incoming orders and modifies, and the trade ids
the engine would hand out.
"""

from exchange.engine.matching import IncomingModify, IncomingOrder
from helpers.instruments import INSTRUMENT_ID
from helpers.participants import make_client_order_id
from helpers.times import SEQUENCED_WALL_CLOCK_NS
from protocol.types import (
    ExchangeOrderId,
    InstrumentId,
    OrderType,
    ParticipantId,
    Price,
    Quantity,
    RequestId,
    Side,
    TradeId,
)


def incoming_order(
    participant_id: ParticipantId,
    side: Side,
    *,
    exchange_order_id: ExchangeOrderId,
    price_e2: Price,
    total_e1: Quantity,
    request_id: RequestId,
    client_order_id: str,
    remaining_e1: Quantity | None = None,
    order_type: OrderType = OrderType.LIMIT,
    instrument_id: InstrumentId = INSTRUMENT_ID,
) -> IncomingOrder:
    """An incoming order for `match`, sequenced at SEQUENCED_WALL_CLOCK_NS, with
    `remaining_e1` left of `total_e1`. If `remaining_e1` is not given, nothing has
    filled and all of `total_e1` is left."""
    if remaining_e1 is None:
        remaining_e1 = total_e1
    return IncomingOrder(
        exchange_order_id=exchange_order_id,
        participant_id=participant_id,
        request_id=request_id,
        sequenced_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
        client_order_id=make_client_order_id(client_order_id),
        instrument_id=instrument_id,
        side=side,
        order_type=order_type,
        price_e2=price_e2,
        total_e1=total_e1,
        remaining_e1=remaining_e1,
    )


def incoming_modify(
    *,
    exchange_order_id: ExchangeOrderId,
    new_price_e2: Price,
    new_total_e1: Quantity,
    request_id: RequestId,
) -> IncomingModify:
    """A modify for `modify`, sequenced at SEQUENCED_WALL_CLOCK_NS."""
    return IncomingModify(
        exchange_order_id=exchange_order_id,
        request_id=request_id,
        sequenced_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
        new_price_e2=new_price_e2,
        new_total_e1=new_total_e1,
    )


class TradeIdCounter:
    """Trade ids from 1, as the engine hands them out to matching.

    Make one per test: `match(..., take_trade_id=TradeIdCounter().take_trade_id)`.
    """

    def __init__(self) -> None:
        self._next_trade_id: TradeId = 1

    def take_trade_id(self) -> TradeId:
        trade_id = self._next_trade_id
        self._next_trade_id += 1
        return trade_id
