"""Matching: what an incoming order, a cancel and a modify do to the book.

Every change to the book is made here: an incoming order trading and resting, a
cancel, a modify. What an order's type does with whatever is left is described on
`OrderType`. Matching emits what happened, order by order. It never emits the price
levels a market-data feed shows: the publisher derives those.

It sees the book and what arrives at it, and nothing else: no clock, no order
history, no risk limits. Whatever adds risk has passed the pre-trade checks by the
time it gets here; a cancel needs none, since it only takes risk away.
"""

from collections.abc import Callable
from dataclasses import dataclass

from exchange.engine.book import Book, RestingOrder
from exchange.events import (
    Event,
    OrderCancelledFromBook,
    OrderCancelledInMatching,
    OrderModifiedLosingPriority,
    OrderModifiedRetainingPriority,
    OrderRested,
    Trade,
)
from protocol.types import (
    ClientOrderId,
    ExchangeOrderId,
    InstrumentId,
    Nanos,
    OrderType,
    ParticipantId,
    Price,
    Quantity,
    ReasonCode,
    RequestId,
    Side,
    TradeId,
)


@dataclass(frozen=True, kw_only=True)
class IncomingOrder:
    """An order arriving at the book, before it has traded or rested.

    `total_e1` is the order's total, including what has filled; `remaining_e1` is what
    could still trade. For a new order the two are equal. An order that a modify sends
    back through matching may already have been partially filled.

    `request_id` is the request that brought the order here: the NewOrder that
    created it, or the modify that cost it its queue position. For a market order,
    `price_e2` is its protection price, the worst price it can trade at. It is the
    collar's bound on the order's side.
    """

    exchange_order_id: ExchangeOrderId
    participant_id: ParticipantId
    request_id: RequestId
    sequenced_wall_clock_ns: Nanos
    client_order_id: ClientOrderId
    instrument_id: InstrumentId
    side: Side
    order_type: OrderType
    price_e2: Price
    total_e1: Quantity
    remaining_e1: Quantity


@dataclass(frozen=True, kw_only=True)
class IncomingModify:
    """A modify of a resting order, arriving at the book before it has changed
    anything.

    `new_price_e2` and `new_total_e1` are the ModifyOrder's. The new total includes
    what has filled, as on the wire. So a participant that asks for 8 in total while 4
    trade gets at most 8, whether the modify reaches the book before those 4 trade or
    after.
    """

    exchange_order_id: ExchangeOrderId
    request_id: RequestId
    sequenced_wall_clock_ns: Nanos
    new_price_e2: Price
    new_total_e1: Quantity


def match(
    incoming: IncomingOrder, book: Book, take_trade_id: Callable[[], TradeId]
) -> list[Event]:
    """Match `incoming` against the other side of `book`, and return what happened as
    events.

    It trades while the best order on the other side is within `incoming`'s price,
    until it has filled or that side is empty. It takes the best price first, and at
    each price the earliest order first. Each trade is at the resting order's price: a
    buy at 105 into a resting ask at 100 trades at 100. Each Trade gets the next id
    from `take_trade_id`. A resting order that trades leaves the book once it has
    nothing left; until then it shrinks.

    If the price or an empty side stopped it with something left, one more event
    follows. A limit order rests what it has left: it is added to the book, and the
    event is an OrderRested. Any other
    order is cancelled, and the event is the OrderCancelledInMatching that ends it,
    with the reason code that `_remainder_cancel_reason_code` returns.

    The extension: a FOK order that cannot fill completely trades nothing, and its one
    event is its cancel, FOK_UNFILLABLE.

    An order that fills completely gets nothing after its last Trade.
    """
    # TODO L1: implement this function
    # You change the book with its `add`, `fill` and `remove`; what you `add` is a
    # `RestingOrder`, which `_make_resting_order` builds from `incoming`. You don't
    # need to worry about price-time priority or other internals: the book's methods,
    # like `get_best_order` and `get_queue_ahead_quantity_e1`, give you what you
    # need. The events you need to return can be built using the `_make_..._event`
    # helpers at the bottom of this file, and `_remainder_cancel_reason_code` says
    # why what is left is cancelled.
    #
    # Suggestions:
    # - Implement `_would_cross` first (and make sure to use it).
    # - Start with a limit order into an empty book; once it rests,
    #   `test_a_limit_order_into_an_empty_book_rests_whole` passes.
    # - If you need to debug, `print(book.render_state())` shows the book as the
    #   tests draw it.
    #
    # For the extension, implement `_is_completely_fillable` first; the docstring's
    # paragraph on FOK says what `match` does with its answer.
    if incoming.order_type == OrderType.FOK and not _is_completely_fillable(
        incoming, book
    ):
        reason_code = ReasonCode.FOK_UNFILLABLE
        order_cancelled = _make_order_cancelled_in_matching_event(
            incoming, cancelled_e1=incoming.remaining_e1, reason_code=reason_code
        )
        return [order_cancelled]
    events = []
    remaining_e1 = incoming.remaining_e1
    while remaining_e1 > 0:
        best_order = book.get_best_order(_opposite(incoming.side))
        if best_order is None or not _would_cross(incoming, best_order.price_e2):
            break
        trade_quantity = min(best_order.remaining_e1, remaining_e1)
        remaining_e1 -= trade_quantity
        if trade_quantity == best_order.remaining_e1:
            book.remove(best_order.exchange_order_id)
        else:
            book.fill(best_order.exchange_order_id, quantity_e1=trade_quantity)
        trade_id = take_trade_id()
        tradeEvent = _make_trade_event(
            incoming,
            best_order,
            trade_id=trade_id,
            price_e2=best_order.price_e2,
            quantity_e1=trade_quantity,
            maker_remaining_e1=best_order.remaining_e1 - trade_quantity,
            taker_remaining_e1=remaining_e1,
        )
        events.append(tradeEvent)

    if remaining_e1 > 0:
        if incoming.order_type == OrderType.LIMIT:
            resting_order = _make_resting_order(incoming, remaining_e1=remaining_e1)
            book.add(resting_order)
            print(book.render_state())
            queue_ahead = book.get_queue_ahead_quantity_e1(incoming.exchange_order_id)
            order_resting = _make_order_rested_event(
                incoming,
                remaining_e1=remaining_e1,
                queue_ahead_quantity_e1=queue_ahead,
            )
            events.append(order_resting)
            return events
        else:
            reason_code = _remainder_cancel_reason_code(incoming, book)
            order_cancelled = _make_order_cancelled_in_matching_event(
                incoming, cancelled_e1=remaining_e1, reason_code=reason_code
            )
            events.append(order_cancelled)
            return events
    return events
    # raise NotImplementedError("L1: match is yours to write")


def cancel(
    exchange_order_id: ExchangeOrderId,
    book: Book,
    *,
    request_id: RequestId,
    reason_code: ReasonCode,
) -> OrderCancelledFromBook:
    """Take the order out of the book; the OrderCancelledFromBook says what it had
    left. Raises KeyError if it is not in the book."""
    # TODO L1: implement this function
    # No need to build an event by hand: there are builders at the bottom of this
    # file for all relevant events.
    print(f"Cancel order with exchange_order_id: {exchange_order_id}")
    resting_order = book.get_order(exchange_order_id)
    book.remove(exchange_order_id)
    canceled_order = _make_order_cancelled_from_book_event(
        resting_order, reason_code=reason_code, request_id=request_id
    )

    return canceled_order
    # raise NotImplementedError("L1: cancel is yours to write")


def modify(
    incoming_modify: IncomingModify, book: Book, take_trade_id: Callable[[], TradeId]
) -> list[Event]:
    """Apply `incoming_modify` to its resting order, and return what happened as events.

    One of three things happens:

    - If the new total is at or below what has already filled, nothing is left to
      trade. The order is cancelled, and the one event is its OrderCancelledFromBook,
      with MODIFY_BELOW_FILLED.
    - If the price stays the same and the order has no more left than before, it keeps
      its queue position, with its new total and what remains of it. The one event is
      an OrderModifiedRetainingPriority.
    - Otherwise the order loses its queue position. It leaves the book, and an
      OrderModifiedLosingPriority says so. What remains of the new total then goes
      through `match` as an incoming limit order at the new price, and `match`'s
      events follow. So if the new price crosses the other side, the order trades
      before any of it rests.

    Raises KeyError if the order is not in the book.
    """
    # TODO L1: implement this function
    # The quantities you need are the resting order's `total_e1` and `remaining_e1`,
    # and the modify's `new_total_e1`. The book gives you the order as it rests, with
    # `get_order`, and `amend` and `remove` change it. You don't need to reimplement
    # what you've already written: `cancel` and `match` do their part here, and
    # `_make_incoming_order_after_modify` turns an order that has lost its queue
    # position into an incoming order for `match`.
    #
    # Suggestions:
    # - Write `cancel` and `match` first: `modify` builds on both.
    # - Start with `test_a_modify_that_changes_nothing_keeps_its_queue_position`, an
    #   order that keeps its queue position.
    print(f"Modify order with exchange_order_id: {incoming_modify.exchange_order_id}")
    events = []
    resting_order = book.get_order(incoming_modify.exchange_order_id)

    filled_e1 = resting_order.total_e1 - resting_order.remaining_e1
    new_remaining_e1 = incoming_modify.new_total_e1 - filled_e1
    if incoming_modify.new_total_e1 <= filled_e1:
        reason_code = ReasonCode.MODIFY_BELOW_FILLED
        order_cancelled = cancel(
            incoming_modify.exchange_order_id,
            book,
            request_id=incoming_modify.request_id,
            reason_code=reason_code,
        )

        events.append(order_cancelled)
        return events

    if (
        incoming_modify.new_price_e2 == resting_order.price_e2
        and new_remaining_e1 <= resting_order.remaining_e1
    ):
        modified_order = _make_order_modified_retaining_priority_event(
            resting_order,
            incoming_modify,
            remaining_e1=new_remaining_e1,
        )
        book.amend(
            incoming_modify.exchange_order_id,
            total_e1=incoming_modify.new_total_e1,
            remaining_e1=modified_order.remaining_e1,
        )
        events.append(modified_order)
        return events
    else:
        modified_order = _make_order_modified_losing_priority_event(
            resting_order, incoming_modify
        )
        book.remove(incoming_modify.exchange_order_id)
        events.append(modified_order)
        incoming_after_modify = _make_incoming_order_after_modify(
            resting_order,
            incoming_modify,
            remaining_e1=new_remaining_e1,
        )
        match_events = match(incoming_after_modify, book, take_trade_id)
        events.extend(match_events)
        return events
    # raise NotImplementedError("L1: modify is yours to write")


def _opposite(side: Side) -> Side:
    return Side.SELL if side is Side.BUY else Side.BUY


def _would_cross(incoming: IncomingOrder, resting_price_e2: Price) -> bool:
    """Whether `incoming` would trade with a resting order at `resting_price_e2`: a buy
    pays at most its price, a sell receives at least its price."""
    print(f"incoming order is: {incoming}")
    print(f"resting price is: {resting_price_e2}")
    if incoming.side == Side.BUY:
        return resting_price_e2 <= incoming.price_e2

    elif incoming.side == Side.SELL:
        return resting_price_e2 >= incoming.price_e2


def _remainder_cancel_reason_code(incoming: IncomingOrder, book: Book) -> ReasonCode:
    """The reason code for cancelling what `incoming` has left after matching, read
    from `book` as matching left it:

    - a market order with nothing left on the other side to trade with:
      MARKET_REMAINDER;
    - a market order stopped by its protection price: PRICE_OUTSIDE_COLLAR;
    - an IOC: IOC_REMAINDER.

    It is never called for a FOK, which has nothing left by then, or for a limit
    order, which rests what it has left.
    """
    if incoming.order_type is OrderType.FOK:
        raise AssertionError(
            "_remainder_cancel_reason_code should never receive a FOK order, as a FOK "
            "should either fill completely or not at all. If this assert triggers, "
            "either you inadvertently called it for a FOK, or you did not call "
            "_is_completely_fillable on it, or your implementation of "
            "_is_completely_fillable has a bug.\n"
            f"FOK order {incoming.exchange_order_id}: a {incoming.side.name} of "
            f"{incoming.remaining_e1} at {incoming.price_e2}.\n"
            f"The book as matching left it:\n{book.render_state()}"
        )
    if incoming.order_type is OrderType.MARKET:
        has_book_run_out = book.get_best_order(_opposite(incoming.side)) is None
        if has_book_run_out:
            return ReasonCode.MARKET_REMAINDER
        return ReasonCode.PRICE_OUTSIDE_COLLAR
    if incoming.order_type is OrderType.IOC:
        return ReasonCode.IOC_REMAINDER
    raise AssertionError(
        "_remainder_cancel_reason_code should never receive a limit order, as a limit "
        "order rests what it has left. If this assert triggers, you called it for a "
        "limit order's remainder.\n"
        f"Limit order {incoming.exchange_order_id}: a {incoming.side.name} of "
        f"{incoming.remaining_e1} at {incoming.price_e2}.\n"
        f"The book as matching left it:\n{book.render_state()}"
    )


def _is_completely_fillable(incoming: IncomingOrder, book: Book) -> bool:
    """Whether `incoming` would fill all it has remaining at once against what rests
    on the other side within its price: the fill-or-kill lookahead. It changes nothing
    in the book."""
    # TODO L1, extension: implement this function - optional
    # The book's `get_orders_best_first` gives you the resting orders on the other
    # side in price-time priority order, and your `_would_cross` says which of those
    # orders are within its price.
    print(
        f"Checking if incoming order {incoming.exchange_order_id} is completely fillable"
    )

    total_fillable_quantity = 0
    resting_orders = book.get_orders_best_first(_opposite(incoming.side))
    for order in resting_orders:
        if not _would_cross(incoming, order.price_e2):
            break
        total_fillable_quantity += order.remaining_e1
        if total_fillable_quantity >= incoming.remaining_e1:
            print(f"Incoming order {incoming.exchange_order_id} is completely fillable")
            return True

    return total_fillable_quantity >= incoming.remaining_e1


def _make_resting_order(
    incoming: IncomingOrder, *, remaining_e1: Quantity
) -> RestingOrder:
    return RestingOrder(
        exchange_order_id=incoming.exchange_order_id,
        participant_id=incoming.participant_id,
        client_order_id=incoming.client_order_id,
        instrument_id=incoming.instrument_id,
        side=incoming.side,
        price_e2=incoming.price_e2,
        total_e1=incoming.total_e1,
        remaining_e1=remaining_e1,
    )


def _make_order_rested_event(
    incoming: IncomingOrder,
    *,
    remaining_e1: Quantity,
    queue_ahead_quantity_e1: Quantity,
) -> OrderRested:
    return OrderRested(
        participant_id=incoming.participant_id,
        exchange_order_id=incoming.exchange_order_id,
        instrument_id=incoming.instrument_id,
        side=incoming.side,
        price_e2=incoming.price_e2,
        remaining_e1=remaining_e1,
        queue_ahead_quantity_e1=queue_ahead_quantity_e1,
    )


def _make_trade_event(
    incoming: IncomingOrder,
    resting: RestingOrder,
    *,
    trade_id: TradeId,
    price_e2: Price,
    quantity_e1: Quantity,
    maker_remaining_e1: Quantity,
    taker_remaining_e1: Quantity,
) -> Trade:
    return Trade(
        trade_id=trade_id,
        instrument_id=incoming.instrument_id,
        price_e2=price_e2,
        quantity_e1=quantity_e1,
        aggressor_side=incoming.side,
        trade_wall_clock_ns=incoming.sequenced_wall_clock_ns,
        maker_participant_id=resting.participant_id,
        maker_client_order_id=resting.client_order_id,
        maker_exchange_order_id=resting.exchange_order_id,
        maker_remaining_e1=maker_remaining_e1,
        taker_participant_id=incoming.participant_id,
        taker_client_order_id=incoming.client_order_id,
        taker_exchange_order_id=incoming.exchange_order_id,
        taker_remaining_e1=taker_remaining_e1,
    )


def _make_order_cancelled_in_matching_event(
    incoming: IncomingOrder, cancelled_e1: Quantity, reason_code: ReasonCode
) -> OrderCancelledInMatching:
    """`cancelled_e1` is what `incoming` has left when it is cancelled, all of which the
    cancel takes."""
    return OrderCancelledInMatching(
        participant_id=incoming.participant_id,
        request_id=incoming.request_id,
        client_order_id=incoming.client_order_id,
        exchange_order_id=incoming.exchange_order_id,
        instrument_id=incoming.instrument_id,
        cancelled_e1=cancelled_e1,
        reason_code=reason_code,
    )


def _make_order_cancelled_from_book_event(
    resting: RestingOrder, *, request_id: RequestId, reason_code: ReasonCode
) -> OrderCancelledFromBook:
    return OrderCancelledFromBook(
        participant_id=resting.participant_id,
        request_id=request_id,
        client_order_id=resting.client_order_id,
        exchange_order_id=resting.exchange_order_id,
        instrument_id=resting.instrument_id,
        cancelled_e1=resting.remaining_e1,
        reason_code=reason_code,
    )


def _make_order_modified_retaining_priority_event(
    resting: RestingOrder, incoming_modify: IncomingModify, *, remaining_e1: Quantity
) -> OrderModifiedRetainingPriority:
    return OrderModifiedRetainingPriority(
        participant_id=resting.participant_id,
        request_id=incoming_modify.request_id,
        client_order_id=resting.client_order_id,
        exchange_order_id=resting.exchange_order_id,
        instrument_id=resting.instrument_id,
        price_e2=incoming_modify.new_price_e2,
        total_e1=incoming_modify.new_total_e1,
        remaining_e1=remaining_e1,
    )


def _make_order_modified_losing_priority_event(
    resting: RestingOrder, incoming_modify: IncomingModify
) -> OrderModifiedLosingPriority:
    return OrderModifiedLosingPriority(
        participant_id=resting.participant_id,
        request_id=incoming_modify.request_id,
        client_order_id=resting.client_order_id,
        exchange_order_id=resting.exchange_order_id,
        instrument_id=resting.instrument_id,
        price_e2=incoming_modify.new_price_e2,
        total_e1=incoming_modify.new_total_e1,
    )


def _make_incoming_order_after_modify(
    resting: RestingOrder, incoming_modify: IncomingModify, *, remaining_e1: Quantity
) -> IncomingOrder:
    return IncomingOrder(
        exchange_order_id=resting.exchange_order_id,
        participant_id=resting.participant_id,
        request_id=incoming_modify.request_id,
        sequenced_wall_clock_ns=incoming_modify.sequenced_wall_clock_ns,
        client_order_id=resting.client_order_id,
        instrument_id=resting.instrument_id,
        side=resting.side,
        # Only a limit order rests.
        order_type=OrderType.LIMIT,
        price_e2=incoming_modify.new_price_e2,
        total_e1=incoming_modify.new_total_e1,
        remaining_e1=remaining_e1,
    )
