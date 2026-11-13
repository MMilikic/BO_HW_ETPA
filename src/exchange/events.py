"""What the engine can decide: the events.

Emitted in order for each command it handles. An event has happened: the engine
decided it, and nothing refuses it. Each carries what the publisher needs from it, and
the participants it concerns, whom the publisher routes to.
"""

from dataclasses import dataclass

from protocol.types import (
    ClientOrderId,
    ExchangeOrderId,
    InstrumentId,
    Nanos,
    ParticipantId,
    Price,
    Quantity,
    ReasonCode,
    RequestId,
    Side,
    TradeId,
)


@dataclass(frozen=True, kw_only=True)
class OrderRested:
    """What is left of an incoming order joins the back of the queue at its price,
    behind `queue_ahead_quantity_e1`. A modify that keeps the order's priority emits
    no second OrderRested.

    No wire message: a venue does not tell a participant its queue position. Nothing
    in the venue reads it either; it is there for the tests and the exercises.
    """

    participant_id: ParticipantId
    exchange_order_id: ExchangeOrderId
    instrument_id: InstrumentId
    side: Side
    price_e2: Price
    remaining_e1: Quantity
    queue_ahead_quantity_e1: Quantity


@dataclass(frozen=True, kw_only=True)
class Trade:
    """One match between a resting order, the maker, and an incoming one, the taker.

    It becomes one PublicTrade and a Fill to each side. `trade_wall_clock_ns` is the
    `sequenced_wall_clock_ns` of the command that brought the taker.
    """

    trade_id: TradeId
    instrument_id: InstrumentId
    price_e2: Price
    quantity_e1: Quantity
    aggressor_side: Side
    trade_wall_clock_ns: Nanos
    maker_participant_id: ParticipantId
    maker_client_order_id: ClientOrderId
    maker_exchange_order_id: ExchangeOrderId
    maker_remaining_e1: Quantity
    taker_participant_id: ParticipantId
    taker_client_order_id: ClientOrderId
    taker_exchange_order_id: ExchangeOrderId
    taker_remaining_e1: Quantity


@dataclass(frozen=True, kw_only=True)
class OrderCancelledFromBook:
    """A resting order was cancelled and has left the book; `cancelled_e1` is what it
    had left, all of which the cancel took. Becomes an OrderCancelled on the wire."""

    participant_id: ParticipantId
    request_id: RequestId
    client_order_id: ClientOrderId
    exchange_order_id: ExchangeOrderId
    instrument_id: InstrumentId
    cancelled_e1: Quantity
    reason_code: ReasonCode


@dataclass(frozen=True, kw_only=True)
class OrderCancelledInMatching:
    """What was left of an incoming order was cancelled instead of resting; the book
    does not change. `cancelled_e1` is that remainder: all of a FOK that could not
    fill, what an IOC or a market order did not trade. Becomes an OrderCancelled on
    the wire.
    """

    participant_id: ParticipantId
    request_id: RequestId
    client_order_id: ClientOrderId
    exchange_order_id: ExchangeOrderId
    instrument_id: InstrumentId
    cancelled_e1: Quantity
    reason_code: ReasonCode


@dataclass(frozen=True, kw_only=True)
class OrderModifiedRetainingPriority:
    """A modify that kept the order's queue position. `total_e1` is its new total, and
    `remaining_e1` what it has left. Becomes an OrderModified on the wire.
    """

    participant_id: ParticipantId
    request_id: RequestId
    client_order_id: ClientOrderId
    exchange_order_id: ExchangeOrderId
    instrument_id: InstrumentId
    price_e2: Price
    total_e1: Quantity
    remaining_e1: Quantity


@dataclass(frozen=True, kw_only=True)
class OrderModifiedLosingPriority:
    """Any other modify. The order leaves the book and goes back through matching as
    an incoming order: its trades follow, then an OrderRested or an
    OrderCancelledInMatching. `total_e1` is the order's new total. Becomes an
    OrderModified on the wire.
    """

    participant_id: ParticipantId
    request_id: RequestId
    client_order_id: ClientOrderId
    exchange_order_id: ExchangeOrderId
    instrument_id: InstrumentId
    price_e2: Price
    total_e1: Quantity


Event = (
    OrderRested
    | Trade
    | OrderCancelledFromBook
    | OrderCancelledInMatching
    | OrderModifiedRetainingPriority
    | OrderModifiedLosingPriority
)
