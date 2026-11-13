"""Builders for the tests of the book, and of what uses it: orders resting in the
book.
"""

from exchange.engine.book import RestingOrder
from helpers.instruments import INSTRUMENT_ID
from helpers.participants import make_client_order_id
from protocol.types import (
    ExchangeOrderId,
    InstrumentId,
    ParticipantId,
    Price,
    Quantity,
    Side,
)


def resting_order(
    participant_id: ParticipantId,
    side: Side,
    *,
    exchange_order_id: ExchangeOrderId,
    price_e2: Price,
    total_e1: Quantity,
    client_order_id: str,
    remaining_e1: Quantity | None = None,
    instrument_id: InstrumentId = INSTRUMENT_ID,
) -> RestingOrder:
    """An order resting with `remaining_e1` left of `total_e1`. If `remaining_e1` is
    not given, nothing has filled and all of `total_e1` is left."""
    if remaining_e1 is None:
        remaining_e1 = total_e1
    return RestingOrder(
        exchange_order_id=exchange_order_id,
        participant_id=participant_id,
        client_order_id=make_client_order_id(client_order_id),
        instrument_id=instrument_id,
        side=side,
        price_e2=price_e2,
        total_e1=total_e1,
        remaining_e1=remaining_e1,
    )
