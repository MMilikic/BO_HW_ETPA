"""The text each `render_state()` is drawn with.

Each component writes its own `render_state()`, because only it knows how it stores
its state. None of them invents the text: this module draws it, so a correct book
renders the same whoever wrote it, and a test can compare a rendered state with a
ladder typed into the test.

It draws what it is given and never sorts. Putting the book in order is the
caller's job, and a renderer that sorted would hide exactly the priority bugs a test
exists to catch. The output is plain ASCII, one line per price or per order, nothing
aligned across lines, so that a ladder can be typed by hand. Every rendering ends
with a newline.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from protocol.types import (
    ExchangeOrderId,
    ParticipantId,
    Price,
    Quantity,
)

BOOK_LEGEND = (
    "price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first"
)


@dataclass(frozen=True, kw_only=True)
class OrderLine:
    """One order in a queue in the engine's book."""

    exchange_order_id: ExchangeOrderId
    participant_id: ParticipantId
    remaining_e1: Quantity


@dataclass(frozen=True, kw_only=True)
class QueueAtPrice:
    """One price in the engine's book, its orders front of the queue first."""

    price_e2: Price
    order_lines: tuple[OrderLine, ...]


def render_book(bids: Sequence[QueueAtPrice], asks: Sequence[QueueAtPrice]) -> str:
    """The engine's book as a ladder, under its legend.

    Both sides are given best price first. The bids are drawn in the order given
    and the asks mirrored, so the two best prices meet in the middle, as on a
    trading screen:

        price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
        asks
          102: #4 (p1) 5
          101: #2 (p2) 10, #3 (p1) 4
        bids
          100: #1 (p1) 10
    """
    bid_lines = [_render_queue_at_price(queue_at_price) for queue_at_price in bids]
    ask_lines = [_render_queue_at_price(queue_at_price) for queue_at_price in asks]
    return _ladder(BOOK_LEGEND, bid_lines=bid_lines, ask_lines=ask_lines)


def _ladder(legend: str, *, bid_lines: list[str], ask_lines: list[str]) -> str:
    lines = [legend, "asks"]
    lines.extend(f"  {line}" for line in reversed(ask_lines))
    lines.append("bids")
    lines.extend(f"  {line}" for line in bid_lines)
    return "\n".join(lines) + "\n"


def _render_queue_at_price(queue_at_price: QueueAtPrice) -> str:
    rendered_orders = ", ".join(
        f"#{order_line.exchange_order_id} (p{order_line.participant_id}) "
        f"{order_line.remaining_e1}"
        for order_line in queue_at_price.order_lines
    )
    return f"{queue_at_price.price_e2}: {rendered_orders}"
