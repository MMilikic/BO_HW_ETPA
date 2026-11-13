"""The order book: the orders resting on one instrument, in price-time priority.

A container with an ordering, and nothing more. It holds what rests and in which
order. Matching decides whether an incoming order crosses. What happened to an order
after it left the book is the order store's concern, and risk is the controls'
concern.

Priority is price first, then the order in which orders reached the book. The engine
handles commands in sequence order, so reaching the book first means having the
earlier sequence number: there is no timestamp here to sort by, and no priority key
for a caller to get wrong.

Every resting order shows all of its quantity. That is a simplification: a real
venue also rests icebergs, orders that show only part of what they hold.
"""

from collections import deque
from dataclasses import dataclass, replace

from exchange.rendering import OrderLine, QueueAtPrice, render_book
from protocol.types import (
    ClientOrderId,
    ExchangeOrderId,
    InstrumentId,
    ParticipantId,
    Price,
    Quantity,
    Side,
)


@dataclass(frozen=True, kw_only=True)
class RestingOrder:
    """An order sitting in the book.

    `total_e1` is the order's total, including what has filled; `remaining_e1` is what
    could still trade.

    Frozen, so it changes only through the book's methods and the book always knows
    what it holds.
    """

    exchange_order_id: ExchangeOrderId
    participant_id: ParticipantId
    client_order_id: ClientOrderId
    instrument_id: InstrumentId
    side: Side
    price_e2: Price
    total_e1: Quantity
    remaining_e1: Quantity


class Book:
    """It raises when its caller has a bug: its callers check before they ask."""

    def __init__(self) -> None:
        self._queues_by_side_and_price_e2: dict[
            Side, dict[Price, deque[ExchangeOrderId]]
        ] = {
            Side.BUY: {},
            Side.SELL: {},
        }
        self._orders_by_exchange_order_id: dict[ExchangeOrderId, RestingOrder] = {}

    def add(self, order: RestingOrder) -> None:
        """Put `order` at the back of the queue at its price.

        Raises ValueError, and changes nothing, if the order:

        - is already in the book;
        - has nothing remaining;
        - has more remaining than its total;
        - would cross the book: a buy at or above the best ask, a sell at or below the
          best bid.

        The book is never crossed, not even locked; matching trades a crossing order
        before it rests.
        """
        if order.exchange_order_id in self._orders_by_exchange_order_id:
            raise ValueError(
                self._error_text(
                    "Book.add should never receive an order that is already in the "
                    "book: an order rests in one place. If this triggers, your "
                    f"matching code added order {order.exchange_order_id} a second "
                    "time.",
                    order,
                )
            )
        if order.remaining_e1 <= 0:
            raise ValueError(
                self._error_text(
                    "Book.add should never receive an order with nothing remaining: "
                    "only an order with something left rests. If this triggers, your "
                    f"matching code rested order {order.exchange_order_id} after it "
                    "had filled completely.",
                    order,
                )
            )
        if order.remaining_e1 > order.total_e1:
            raise ValueError(
                self._error_text(
                    "Book.add should never receive an order with more remaining than "
                    "its total, which includes what has filled. If this triggers, "
                    f"your matching code gave order {order.exchange_order_id} a "
                    f"remaining of {order.remaining_e1} out of a total of "
                    f"{order.total_e1}.",
                    order,
                )
            )
        best_opposite_order = self.get_best_order(_opposite(order.side))
        if best_opposite_order is not None and _would_lock_or_cross(
            order, best_opposite_order.price_e2
        ):
            raise ValueError(
                self._error_text(
                    "Book.add should never receive an order that would cross the "
                    "book: matching trades a crossing order before it rests. If this "
                    "triggers, your matching code rested order "
                    f"{order.exchange_order_id}, which could still trade with order "
                    f"{best_opposite_order.exchange_order_id}, on the other side at "
                    f"{best_opposite_order.price_e2}.",
                    order,
                )
            )
        queues_by_price_e2 = self._queues_by_side_and_price_e2[order.side]
        queue = queues_by_price_e2.get(order.price_e2)
        if queue is None:
            queue = deque()
            queues_by_price_e2[order.price_e2] = queue
        queue.append(order.exchange_order_id)
        self._orders_by_exchange_order_id[order.exchange_order_id] = order

    def remove(self, exchange_order_id: ExchangeOrderId) -> RestingOrder:
        """Take the order out of the book and return it as it was.

        Raises KeyError if it is not in the book.
        """
        order = self.get_order(exchange_order_id)
        queues_by_price_e2 = self._queues_by_side_and_price_e2[order.side]
        queue = queues_by_price_e2[order.price_e2]
        queue.remove(exchange_order_id)
        if not queue:
            del queues_by_price_e2[order.price_e2]
        del self._orders_by_exchange_order_id[exchange_order_id]
        return order

    def fill(
        self, exchange_order_id: ExchangeOrderId, *, quantity_e1: Quantity
    ) -> None:
        """Record that `quantity_e1` of the order traded. The quantity comes off what
        the order has left, and the order keeps its total and its queue position.

        Raises ValueError if `quantity_e1` is not positive, or if nothing would
        remain; KeyError if the order is not in the book.
        """
        order = self.get_order(exchange_order_id)
        if quantity_e1 <= 0:
            raise ValueError(
                self._error_text(
                    "Book.fill should never receive a quantity that is not positive: "
                    "a trade always moves something. If this triggers, your matching "
                    f"code filled order {exchange_order_id} with {quantity_e1}.",
                    order,
                )
            )
        remaining_e1 = order.remaining_e1 - quantity_e1
        if remaining_e1 <= 0:
            raise ValueError(
                self._error_text(
                    "Book.fill should never use up an order: an order that is used "
                    "up is removed, not filled. If this triggers, your matching code "
                    f"filled order {exchange_order_id} with {quantity_e1}, and it had "
                    f"{order.remaining_e1} left.",
                    order,
                )
            )
        self._orders_by_exchange_order_id[exchange_order_id] = replace(
            order, remaining_e1=remaining_e1
        )

    def amend(
        self,
        exchange_order_id: ExchangeOrderId,
        *,
        total_e1: Quantity,
        remaining_e1: Quantity,
    ) -> None:
        """Give the order a total of `total_e1`, with `remaining_e1` left, keeping its
        queue position. This is what a modify that keeps the order's queue position does
        to the book.

        Raises ValueError if `remaining_e1` is not positive, if it is more than the
        order has left, or if the amend would change what has filled. Raises KeyError
        if the order is not in the book.
        """
        order = self.get_order(exchange_order_id)
        if remaining_e1 <= 0:
            raise ValueError(
                self._error_text(
                    "Book.amend should never leave an order with nothing remaining: "
                    "a modify that leaves nothing is a cancel. If this triggers, "
                    f"your matching code amended order {exchange_order_id} to "
                    f"{remaining_e1} remaining.",
                    order,
                )
            )
        if remaining_e1 > order.remaining_e1:
            raise ValueError(
                self._error_text(
                    "Book.amend should never grow what an order has left: an order "
                    "that grows loses its queue position, and is removed and added "
                    "again. If this triggers, your matching code amended order "
                    f"{exchange_order_id} from {order.remaining_e1} left to "
                    f"{remaining_e1}.",
                    order,
                )
            )
        filled_e1 = order.total_e1 - order.remaining_e1
        filled_after_amend_e1 = total_e1 - remaining_e1
        if filled_after_amend_e1 != filled_e1:
            raise ValueError(
                self._error_text(
                    "Book.amend should never change what an order has filled: a modify "
                    "never does. If this triggers, your matching code amended order "
                    f"{exchange_order_id} to a total of {total_e1} with {remaining_e1} "
                    f"remaining, which would make {filled_after_amend_e1} filled "
                    f"instead of {filled_e1}.",
                    order,
                )
            )
        self._orders_by_exchange_order_id[exchange_order_id] = replace(
            order, total_e1=total_e1, remaining_e1=remaining_e1
        )

    def get_best_order(self, side: Side) -> RestingOrder | None:
        """The order at the front of the queue at the side's best price, if any."""
        queues_by_price_e2 = self._queues_by_side_and_price_e2[side]
        if not queues_by_price_e2:
            return None
        best_price_e2 = (
            max(queues_by_price_e2) if side is Side.BUY else min(queues_by_price_e2)
        )
        front_exchange_order_id = queues_by_price_e2[best_price_e2][0]
        return self._orders_by_exchange_order_id[front_exchange_order_id]

    def get_orders_best_first(self, side: Side) -> list[RestingOrder]:
        """The side's orders in priority order, `get_best_order(side)` first.

        A new list, so changing the book afterwards does not change it.
        """
        queues_by_price_e2 = self._queues_by_side_and_price_e2[side]
        orders = []
        for price_e2 in self._get_prices_best_first(side):
            for exchange_order_id in queues_by_price_e2[price_e2]:
                orders.append(self._orders_by_exchange_order_id[exchange_order_id])
        return orders

    def get_queue_ahead_quantity_e1(
        self, exchange_order_id: ExchangeOrderId
    ) -> Quantity:
        """How much quantity rests ahead of the order at its price.

        Zero for the order at the front. Raises KeyError if it is not in the book.
        """
        order = self.get_order(exchange_order_id)
        queue_ahead_quantity_e1 = 0
        queue = self._queues_by_side_and_price_e2[order.side][order.price_e2]
        for queued_exchange_order_id in queue:
            if queued_exchange_order_id == exchange_order_id:
                return queue_ahead_quantity_e1
            queue_ahead_quantity_e1 += self._orders_by_exchange_order_id[
                queued_exchange_order_id
            ].remaining_e1
        raise AssertionError(
            f"order {exchange_order_id} is in the book but not in the queue at "
            f"{order.price_e2}"
        )

    def get_order(self, exchange_order_id: ExchangeOrderId) -> RestingOrder:
        """The order as it rests. Raises KeyError if it is not in the book."""
        order = self._orders_by_exchange_order_id.get(exchange_order_id)
        if order is None:
            raise KeyError(f"order {exchange_order_id} is not in the book")
        return order

    def render_state(self) -> str:
        """The book as a ladder, drawn by `rendering.render_book`: each side best price
        first, and at each price the front of the queue first.

        Two books built by the same operations in the same order render identically.
        """
        bids = self._get_queues_at_price(Side.BUY)
        asks = self._get_queues_at_price(Side.SELL)
        return render_book(bids=bids, asks=asks)

    def _error_text(self, sentence: str, order: RestingOrder) -> str:
        """The text of an error the book raises. It starts with `sentence`, which says
        what the call should never receive and why. Then come the order and the book as
        they stand, since a call that raises changes nothing."""
        return (
            f"{sentence}\n"
            f"Order {order.exchange_order_id}: a {order.side.name} at "
            f"{order.price_e2}, {order.remaining_e1} remaining of a total of "
            f"{order.total_e1}.\nThe book:\n{self.render_state()}"
        )

    def _get_prices_best_first(self, side: Side) -> list[Price]:
        is_highest_first = side is Side.BUY
        return sorted(self._queues_by_side_and_price_e2[side], reverse=is_highest_first)

    def _get_queues_at_price(self, side: Side) -> list[QueueAtPrice]:
        queues_at_price = []
        for price_e2 in self._get_prices_best_first(side):
            order_lines = [
                self._make_order_line(exchange_order_id)
                for exchange_order_id in self._queues_by_side_and_price_e2[side][
                    price_e2
                ]
            ]
            queues_at_price.append(
                QueueAtPrice(price_e2=price_e2, order_lines=tuple(order_lines))
            )
        return queues_at_price

    def _make_order_line(self, exchange_order_id: ExchangeOrderId) -> OrderLine:
        order = self._orders_by_exchange_order_id[exchange_order_id]
        return OrderLine(
            exchange_order_id=order.exchange_order_id,
            participant_id=order.participant_id,
            remaining_e1=order.remaining_e1,
        )


def _opposite(side: Side) -> Side:
    return Side.SELL if side is Side.BUY else Side.BUY


def _would_lock_or_cross(order: RestingOrder, best_opposite_price_e2: Price) -> bool:
    if order.side is Side.BUY:
        return order.price_e2 >= best_opposite_price_e2
    return order.price_e2 <= best_opposite_price_e2
