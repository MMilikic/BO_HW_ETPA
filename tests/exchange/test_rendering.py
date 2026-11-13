"""rendering.py: the one text format every render_state() is drawn in.

Tests throughout the exchange type these ladders out literally, so the format is
written out here, character for character.
"""

from textwrap import dedent

from exchange.rendering import (
    OrderLine,
    QueueAtPrice,
    render_book,
)
from helpers.participants import A, B
from protocol.types import (
    Price,
)

# The tests are grouped in a class per function, and a function's class comes before
# the classes of the functions that call it. A failure's header names its class, so
# it says which function to look at; and with the order, the first failure is usually
# the one to fix first. The classes hold nothing but the tests.


class Test_render_book:
    def test_a_two_sided_book_renders_exactly_as_the_docstring_shows(
        self,
    ) -> None:
        bids = [
            QueueAtPrice(
                price_e2=100,
                order_lines=(
                    OrderLine(exchange_order_id=1, participant_id=A, remaining_e1=10),
                ),
            ),
        ]
        asks = [
            QueueAtPrice(
                price_e2=101,
                order_lines=(
                    OrderLine(exchange_order_id=2, participant_id=B, remaining_e1=10),
                    OrderLine(exchange_order_id=3, participant_id=A, remaining_e1=4),
                ),
            ),
            QueueAtPrice(
                price_e2=102,
                order_lines=(
                    OrderLine(exchange_order_id=4, participant_id=A, remaining_e1=5),
                ),
            ),
        ]

        assert render_book(bids=bids, asks=asks) == dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              102: #4 (p1) 5
              101: #2 (p2) 10, #3 (p1) 4
            bids
              100: #1 (p1) 10
            """)

    def test_levels_and_orders_are_drawn_in_the_order_given(self) -> None:
        bids = [
            queue_at_price(
                99, [OrderLine(exchange_order_id=2, participant_id=B, remaining_e1=5)]
            ),
            queue_at_price(
                100,
                [
                    OrderLine(exchange_order_id=4, participant_id=A, remaining_e1=3),
                    OrderLine(exchange_order_id=1, participant_id=A, remaining_e1=10),
                ],
            ),
        ]

        assert render_book(bids=bids, asks=[]) == dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
            bids
              99: #2 (p2) 5
              100: #4 (p1) 3, #1 (p1) 10
            """)

    def test_an_empty_side_is_drawn_as_its_heading_alone(self) -> None:
        asks = [
            queue_at_price(
                101, [OrderLine(exchange_order_id=1, participant_id=A, remaining_e1=10)]
            )
        ]

        assert render_book(bids=[], asks=asks) == dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              101: #1 (p1) 10
            bids
            """)

    def test_the_asks_are_mirrored_so_the_best_prices_meet_in_the_middle(self) -> None:
        bids = [
            queue_at_price(
                100, [OrderLine(exchange_order_id=1, participant_id=A, remaining_e1=10)]
            ),
            queue_at_price(
                99, [OrderLine(exchange_order_id=2, participant_id=A, remaining_e1=10)]
            ),
        ]
        asks = [
            queue_at_price(
                101, [OrderLine(exchange_order_id=3, participant_id=B, remaining_e1=10)]
            ),
            queue_at_price(
                102, [OrderLine(exchange_order_id=4, participant_id=B, remaining_e1=10)]
            ),
        ]

        assert render_book(bids=bids, asks=asks) == dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              102: #4 (p2) 10
              101: #3 (p2) 10
            bids
              100: #1 (p1) 10
              99: #2 (p1) 10
            """)


def queue_at_price(price_e2: Price, order_lines: list[OrderLine]) -> QueueAtPrice:
    return QueueAtPrice(price_e2=price_e2, order_lines=tuple(order_lines))
