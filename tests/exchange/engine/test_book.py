"""book.py: which resting order comes first, where each order stands in its queue, and
that the book never crosses.

Everything here goes through the book's own methods and its render_state(), never its
containers, so the structure inside the book can change without these tests
noticing.
"""

from textwrap import dedent

import pytest

from exchange.engine.book import Book, RestingOrder
from helpers.assertions import assert_ladder
from helpers.book import resting_order
from helpers.participants import A, B
from protocol.types import ExchangeOrderId, ParticipantId, Price, Quantity, Side

EACH_ORDER_THAT_WOULD_CROSS = [
    pytest.param(Side.BUY, 10, id="a buy at the best ask, which locks the book"),
    pytest.param(Side.BUY, 15, id="a buy between the asks"),
    pytest.param(Side.SELL, 0, id="a sell at a best bid of 0, which locks the book"),
    pytest.param(Side.SELL, -5, id="a sell between the bids"),
]
EACH_AMEND_THE_BOOK_REFUSES = [
    pytest.param(4, 0, id="nothing left"),
    pytest.param(12, 8, id="more left than before"),
    pytest.param(5, 5, id="a total of 5 with 5 left, which changes what has filled"),
]
EACH_ORDER_JUST_SHORT_OF_CROSSING = [
    pytest.param(Side.BUY, 9, id="a buy just below the best ask"),
    pytest.param(Side.SELL, 1, id="a sell just above the best bid"),
]


# The tests are grouped in a class per function, and a function's class comes before
# the classes of the functions that call it. A failure's header names its class, so
# it says which function to look at; and with the order, the first failure is usually
# the one to fix first. The classes hold nothing but the tests.


class Test_get_order:
    def test_getting_an_order_shows_what_it_has_left(self) -> None:
        book = Book()
        book.add(ask(B, exchange_order_id=2, price_e2=100, total_e1=10))
        book.add(ask(A, exchange_order_id=1, price_e2=101, total_e1=10))
        book.fill(1, quantity_e1=4)

        order = book.get_order(1)

        assert order == ask(
            A, exchange_order_id=1, price_e2=101, total_e1=10, remaining_e1=6
        ), (
            f"order 1 should rest with a total of 10, of which 6 are left after a fill "
            f"of 4:\n{book.render_state()}"
        )

    def test_getting_an_order_not_in_the_book_raises(self) -> None:
        book = Book()
        book.add(ask(A, exchange_order_id=1, price_e2=101, total_e1=10))
        book.remove(1)

        with pytest.raises(KeyError):
            book.get_order(1)


class Test_get_best_order:
    def test_bids_come_out_highest_price_first(self) -> None:
        """Power prices go negative, and 0 is a real price. Two bugs:
        `if order.price_e2:` loses the bid at 0, and a sort key that ignores the sign
        ranks the bids at -5 and -10 above the bid at 0."""
        book = Book()
        book.add(bid(A, exchange_order_id=1, price_e2=-10, total_e1=10))
        book.add(bid(A, exchange_order_id=2, price_e2=0, total_e1=10))
        book.add(bid(A, exchange_order_id=3, price_e2=-5, total_e1=10))

        assert best_price_e2(book, Side.BUY) == 0, (
            f"a bid at 0 is the highest here:\n{book.render_state()}"
        )
        book.remove(2)
        assert best_price_e2(book, Side.BUY) == -5, (
            f"a bid at -5 is higher than one at -10:\n{book.render_state()}"
        )

    def test_asks_come_out_lowest_price_first(self) -> None:
        """The asks' side of the same trap: -10 is the lowest ask, and 0 is a price."""
        book = Book()
        book.add(ask(A, exchange_order_id=1, price_e2=0, total_e1=10))
        book.add(ask(A, exchange_order_id=2, price_e2=-10, total_e1=10))
        book.add(ask(A, exchange_order_id=3, price_e2=-5, total_e1=10))

        assert best_price_e2(book, Side.SELL) == -10, (
            f"an ask at -10 is the lowest here:\n{book.render_state()}"
        )
        book.remove(2)
        assert best_price_e2(book, Side.SELL) == -5, (
            f"an ask at -5 is lower than one at 0:\n{book.render_state()}"
        )

    def test_at_one_price_the_order_added_first_comes_out_first(self) -> None:
        book = Book()
        book.add(bid(B, exchange_order_id=1, price_e2=100, total_e1=10))
        book.add(bid(A, exchange_order_id=2, price_e2=100, total_e1=10))

        best_order = book.get_best_order(Side.BUY)

        assert best_order is not None, "two bids rest, so there is a best one"
        assert best_order.exchange_order_id == 1, (
            f"at one price, the order that reached the book first is at the front:\n"
            f"{book.render_state()}"
        )


class Test_get_orders_best_first:
    def test_walking_a_side_lists_its_orders_in_price_time_priority(self) -> None:
        book = Book()
        book.add(bid(A, exchange_order_id=1, price_e2=-5, total_e1=10))
        book.add(bid(B, exchange_order_id=2, price_e2=0, total_e1=10))
        book.add(bid(A, exchange_order_id=3, price_e2=-5, total_e1=10))
        book.add(bid(B, exchange_order_id=4, price_e2=-10, total_e1=10))

        bids_best_first = book.get_orders_best_first(Side.BUY)

        assert exchange_order_ids(bids_best_first) == [2, 1, 3, 4], (
            f"best price first (0, then -5, then -10), and at -5 the order that came "
            f"first, 1, before 3:\n{book.render_state()}"
        )


class Test_get_queue_ahead_quantity_e1:
    def test_queue_ahead_counts_quantity_at_its_own_price_only(self) -> None:
        """Only at the order's own price: the ask at 100 trades first, but it is not in
        the queue at 101."""
        book = Book()
        book.add(ask(B, exchange_order_id=1, price_e2=100, total_e1=3))
        book.add(ask(A, exchange_order_id=2, price_e2=101, total_e1=10))
        book.add(ask(B, exchange_order_id=3, price_e2=101, total_e1=4))
        book.add(ask(A, exchange_order_id=4, price_e2=101, total_e1=10))

        assert book.get_queue_ahead_quantity_e1(2) == 0, (
            f"order 2 is at the front of the queue at 101:\n{book.render_state()}"
        )
        assert book.get_queue_ahead_quantity_e1(3) == 10, (
            f"order 2's 10 is ahead of order 3:\n{book.render_state()}"
        )
        assert book.get_queue_ahead_quantity_e1(4) == 14, (
            f"orders 2 and 3 are ahead of order 4: 10 + 4, counted in quantity, not as "
            f"two orders:\n{book.render_state()}"
        )


class Test_add:
    def test_adding_an_order_with_more_left_than_its_total_raises(self) -> None:
        book = Book()

        with pytest.raises(ValueError):
            book.add(
                ask(A, exchange_order_id=1, price_e2=101, total_e1=6, remaining_e1=10)
            )

    @pytest.mark.parametrize(("side", "price_e2"), EACH_ORDER_THAT_WOULD_CROSS)
    def test_adding_an_order_that_would_cross_raises(
        self, side: Side, price_e2: Price
    ) -> None:
        book = book_with_two_levels_a_side()
        crossing_order = resting_order(
            B,
            side,
            exchange_order_id=5,
            price_e2=price_e2,
            total_e1=10,
            client_order_id="order-5",
        )

        with pytest.raises(ValueError):
            book.add(crossing_order)

        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              20: #4 (p2) 10
              10: #3 (p1) 10
            bids
              0: #1 (p1) 10
              -10: #2 (p2) 10
            """),
        )

    @pytest.mark.parametrize(("side", "price_e2"), EACH_ORDER_JUST_SHORT_OF_CROSSING)
    def test_an_order_just_short_of_crossing_rests(
        self, side: Side, price_e2: Price
    ) -> None:
        book = book_with_two_levels_a_side()

        book.add(
            resting_order(
                B,
                side,
                exchange_order_id=5,
                price_e2=price_e2,
                total_e1=10,
                client_order_id="order-5",
            )
        )

        best_order = book.get_best_order(side)
        assert best_order is not None and best_order.exchange_order_id == 5, (
            f"order 5, at {price_e2}, does not cross, so it rests as its side's best "
            f"order:\n{book.render_state()}"
        )

    def test_an_order_removed_and_added_again_goes_to_the_back(self) -> None:
        book = Book()
        book.add(ask(A, exchange_order_id=1, price_e2=101, total_e1=10))
        book.add(ask(B, exchange_order_id=2, price_e2=101, total_e1=10))

        removed_order = book.remove(1)
        book.add(removed_order)

        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              101: #2 (p2) 10, #1 (p1) 10
            bids
            """),
        )


class Test_remove:
    def test_removing_an_order_moves_everyone_behind_it_up(self) -> None:
        book = Book()
        book.add(ask(A, exchange_order_id=1, price_e2=101, total_e1=10))
        book.add(ask(B, exchange_order_id=2, price_e2=101, total_e1=10))
        book.add(ask(A, exchange_order_id=3, price_e2=101, total_e1=10))

        book.remove(1)

        assert book.get_queue_ahead_quantity_e1(2) == 0, (
            f"order 2 is now at the front:\n{book.render_state()}"
        )
        assert book.get_queue_ahead_quantity_e1(3) == 10, (
            f"only order 2 is ahead of order 3:\n{book.render_state()}"
        )

    def test_an_empty_level_disappears(self) -> None:
        book = Book()
        book.add(ask(A, exchange_order_id=1, price_e2=101, total_e1=10))
        book.add(ask(B, exchange_order_id=2, price_e2=102, total_e1=10))

        book.remove(1)

        assert best_price_e2(book, Side.SELL) == 102, (
            f"with nothing left at 101, the best ask is at 102:\n{book.render_state()}"
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              102: #2 (p2) 10
            bids
            """),
        )


class Test_fill:
    def test_a_fill_keeps_queue_position(self) -> None:
        book = Book()
        book.add(ask(A, exchange_order_id=1, price_e2=101, total_e1=10))
        book.add(ask(B, exchange_order_id=2, price_e2=101, total_e1=10))

        book.fill(1, quantity_e1=4)

        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              101: #1 (p1) 6, #2 (p2) 10
            bids
            """),
        )

    def test_a_fill_that_would_leave_nothing_raises(self) -> None:
        book = Book()
        book.add(ask(A, exchange_order_id=1, price_e2=101, total_e1=10))

        with pytest.raises(ValueError):
            book.fill(1, quantity_e1=10)


class Test_amend:
    def test_an_amend_keeps_queue_position(self) -> None:
        """Order 1 has a total of 10, of which 4 have filled, so 6 are left. Amended to
        a total of 8, it has 4 left."""
        book = Book()
        book.add(ask(A, exchange_order_id=1, price_e2=101, total_e1=10, remaining_e1=6))
        book.add(ask(B, exchange_order_id=2, price_e2=101, total_e1=10))

        book.amend(1, total_e1=8, remaining_e1=4)

        assert book.get_order(1) == ask(
            A, exchange_order_id=1, price_e2=101, total_e1=8, remaining_e1=4
        ), (
            f"order 1 should rest with a total of 8, of which 4 are left:\n"
            f"{book.render_state()}"
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              101: #1 (p1) 4, #2 (p2) 10
            bids
            """),
        )

    def test_an_amend_that_changes_nothing_leaves_the_order_as_it_was(self) -> None:
        book = Book()
        book.add(ask(A, exchange_order_id=1, price_e2=101, total_e1=10, remaining_e1=6))

        book.amend(1, total_e1=10, remaining_e1=6)

        assert book.get_order(1) == ask(
            A, exchange_order_id=1, price_e2=101, total_e1=10, remaining_e1=6
        ), f"order 1 should rest as it did before the amend:\n{book.render_state()}"

    @pytest.mark.parametrize(("total_e1", "remaining_e1"), EACH_AMEND_THE_BOOK_REFUSES)
    def test_an_amend_that_the_book_refuses_raises_and_changes_nothing(
        self, total_e1: Quantity, remaining_e1: Quantity
    ) -> None:
        book = Book()
        book.add(ask(A, exchange_order_id=1, price_e2=101, total_e1=10, remaining_e1=6))

        with pytest.raises(ValueError):
            book.amend(1, total_e1=total_e1, remaining_e1=remaining_e1)

        assert book.get_order(1) == ask(
            A, exchange_order_id=1, price_e2=101, total_e1=10, remaining_e1=6
        ), f"order 1 should rest as it did before the amend:\n{book.render_state()}"


class Test_render_state:
    def test_two_books_built_the_same_way_render_the_same(self) -> None:
        first_state = book_with_four_orders().render_state()
        second_state = book_with_four_orders().render_state()

        assert first_state == second_state, (
            "the same operations in the same order must give byte-identical rendered "
            "states"
        )

    def test_render_state_draws_the_book_as_a_ladder(self) -> None:
        """The orders arrive out of price order on both sides. Two bugs: a
        `render_state()` that walks its levels in the order they arrived, or one that
        sorts a side the wrong way."""
        book = Book()
        book.add(bid(A, exchange_order_id=1, price_e2=99, total_e1=10))
        book.add(bid(B, exchange_order_id=2, price_e2=100, total_e1=5))
        book.add(ask(A, exchange_order_id=3, price_e2=102, total_e1=5))
        book.add(ask(B, exchange_order_id=4, price_e2=101, total_e1=10))
        book.add(ask(A, exchange_order_id=5, price_e2=101, total_e1=4))

        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              102: #3 (p1) 5
              101: #4 (p2) 10, #5 (p1) 4
            bids
              100: #2 (p2) 5
              99: #1 (p1) 10
            """),
        )

    def test_the_state_shows_how_much_each_order_has_left(self) -> None:
        filled_book = book_with_four_orders()
        filled_book.fill(2, quantity_e1=1)

        assert filled_book.render_state() != book_with_four_orders().render_state(), (
            "two books that differ only in one order's remaining quantity must render "
            "differently"
        )


def bid(
    participant_id: ParticipantId,
    *,
    exchange_order_id: ExchangeOrderId,
    price_e2: Price,
    total_e1: Quantity,
    remaining_e1: Quantity | None = None,
) -> RestingOrder:
    """A buy for the book, with `remaining_e1` left of `total_e1`. If `remaining_e1` is
    not given, nothing has filled and all of `total_e1` is left.

    Its client order id, which the book never reads, is derived from its exchange
    order id: `order-1` for order 1.
    """
    return resting_order(
        participant_id,
        Side.BUY,
        exchange_order_id=exchange_order_id,
        price_e2=price_e2,
        total_e1=total_e1,
        remaining_e1=remaining_e1,
        client_order_id=f"order-{exchange_order_id}",
    )


def ask(
    participant_id: ParticipantId,
    *,
    exchange_order_id: ExchangeOrderId,
    price_e2: Price,
    total_e1: Quantity,
    remaining_e1: Quantity | None = None,
) -> RestingOrder:
    """A sell for the book, as `bid`."""
    return resting_order(
        participant_id,
        Side.SELL,
        exchange_order_id=exchange_order_id,
        price_e2=price_e2,
        total_e1=total_e1,
        remaining_e1=remaining_e1,
        client_order_id=f"order-{exchange_order_id}",
    )


def book_with_four_orders() -> Book:
    book = Book()
    book.add(bid(A, exchange_order_id=1, price_e2=100, total_e1=10))
    book.add(ask(B, exchange_order_id=2, price_e2=101, total_e1=10))
    book.add(ask(A, exchange_order_id=3, price_e2=101, total_e1=4))
    book.add(ask(A, exchange_order_id=4, price_e2=102, total_e1=5))
    return book


def book_with_two_levels_a_side() -> Book:
    book = Book()
    book.add(bid(A, exchange_order_id=1, price_e2=0, total_e1=10))
    book.add(bid(B, exchange_order_id=2, price_e2=-10, total_e1=10))
    book.add(ask(A, exchange_order_id=3, price_e2=10, total_e1=10))
    book.add(ask(B, exchange_order_id=4, price_e2=20, total_e1=10))
    return book


def best_price_e2(book: Book, side: Side) -> Price | None:
    best_order = book.get_best_order(side)
    if best_order is None:
        return None
    return best_order.price_e2


def exchange_order_ids(orders: list[RestingOrder]) -> list[ExchangeOrderId]:
    return [order.exchange_order_id for order in orders]
