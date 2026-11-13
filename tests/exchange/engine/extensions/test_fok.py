"""matching.py, an extension: FOK orders."""

from textwrap import dedent

from exchange.engine.book import Book
from exchange.engine.matching import IncomingOrder, _is_completely_fillable, match
from exchange.events import OrderCancelledInMatching, Trade
from exchange.extensions import Extension
from helpers.assertions import assert_events, assert_ladder
from helpers.book import resting_order
from helpers.instruments import INSTRUMENT_ID
from helpers.matching import TradeIdCounter, incoming_order
from helpers.participants import A, B, make_client_order_id
from helpers.times import SEQUENCED_WALL_CLOCK_NS
from protocol.types import OrderType, Price, Quantity, ReasonCode, Side

EXTENSION = Extension.FILL_OR_KILL


# The tests are grouped in a class per function, and a function's class comes before
# the classes of the functions that call it. A failure's header names its class, so
# it says which function to look at; and with the order, the first failure is usually
# the one to fix first. The classes hold nothing but the tests.


class Test_is_completely_fillable:
    def test_a_fok_is_fillable_from_what_rests_within_its_price(self) -> None:
        book = book_with_three_asks()

        assert _is_completely_fillable(fok_buy(price_e2=101, total_e1=8), book), (
            "6 at 100 and 4 at 101 rest within 101, enough for 8:\n"
            f"{book.render_state()}"
        )

    def test_a_fok_for_exactly_what_rests_within_its_price_is_fillable(self) -> None:
        """Within 101 the book holds exactly the 10 the FOK wants, and exactly enough is
        enough. The bug is a lookahead that wants more than 10."""
        book = book_with_three_asks()

        assert _is_completely_fillable(fok_buy(price_e2=101, total_e1=10), book), (
            f"6 at 100 and 4 at 101 rest within 101, exactly 10:\n{book.render_state()}"
        )

    def test_a_fok_cannot_count_what_rests_beyond_its_price(self) -> None:
        """A lookahead that ignores the price counts the 5 at 102 too, and finds 15."""
        book = book_with_three_asks()

        assert not _is_completely_fillable(fok_buy(price_e2=101, total_e1=11), book), (
            f"only 10 rest within 101, short of 11:\n{book.render_state()}"
        )

    def test_a_fok_sell_counts_only_the_bids_within_its_price(self) -> None:
        book = book_with_three_bids_below_zero()

        assert _is_completely_fillable(fok_sell(price_e2=-101, total_e1=10), book), (
            f"a FOK sell of 10 at -101 should be fillable: 6 at -100 and 4 at -101 "
            f"rest within -101:\n"
            f"{book.render_state()}"
        )
        assert not _is_completely_fillable(
            fok_sell(price_e2=-101, total_e1=11), book
        ), (
            f"a FOK sell of 11 at -101 should not be fillable: only 10 rest within "
            f"-101:\n{book.render_state()}"
        )

    def test_a_fok_is_not_fillable_from_an_empty_book(self) -> None:
        assert not _is_completely_fillable(fok_buy(price_e2=101, total_e1=1), Book()), (
            "nothing rests, so nothing can fill"
        )

    def test_the_lookahead_changes_nothing_in_the_book(self) -> None:
        """A FOK that turns out not to fill must find the book as it was. The bug is
        counting by taking orders out of the book."""
        book = book_with_three_asks()
        state_before = book.render_state()

        _is_completely_fillable(fok_buy(price_e2=101, total_e1=11), book)

        assert_ladder(book.render_state(), state_before)


class Test_match:
    def test_a_fok_that_cannot_fill_completely_trades_nothing(self) -> None:
        """Within the FOK's price of 101 the book holds 8 over two levels, and the ask
        at 102 would make up the rest. Two bugs: a lookahead that ignores the price, or
        a sweep that fills what it can."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=4,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=2,
                price_e2=101,
                total_e1=4,
                client_order_id="A-2",
            )
        )
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=3,
                price_e2=102,
                total_e1=5,
                client_order_id="A-3",
            )
        )
        fok_buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=4,
            price_e2=101,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
            order_type=OrderType.FOK,
        )

        events = match(fok_buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                OrderCancelledInMatching(
                    participant_id=B,
                    request_id=1,
                    client_order_id=make_client_order_id("B-1"),
                    exchange_order_id=4,
                    instrument_id=INSTRUMENT_ID,
                    cancelled_e1=10,
                    reason_code=ReasonCode.FOK_UNFILLABLE,
                ),
            ],
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              102: #3 (p1) 5
              101: #2 (p1) 4
              100: #1 (p1) 4
            bids
            """),
        )

    def test_a_fok_sell_that_cannot_fill_within_its_price_trades_nothing(self) -> None:
        """Within -101 the bids hold 10, short of 11, and the bid at -102 would make up
        the rest. Two bugs: trading the 10 and cancelling the 1, or skipping the
        lookahead."""
        book = book_with_three_bids_below_zero()

        events = match(
            fok_sell(price_e2=-101, total_e1=11),
            book,
            take_trade_id=TradeIdCounter().take_trade_id,
        )

        assert_events(
            events,
            [
                OrderCancelledInMatching(
                    participant_id=B,
                    request_id=1,
                    client_order_id=make_client_order_id("B-1"),
                    exchange_order_id=4,
                    instrument_id=INSTRUMENT_ID,
                    cancelled_e1=11,
                    reason_code=ReasonCode.FOK_UNFILLABLE,
                ),
            ],
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
            bids
              -100: #1 (p1) 6
              -101: #2 (p1) 4
              -102: #3 (p1) 5
            """),
        )

    def test_a_fok_that_can_fill_across_two_levels_fills_completely(self) -> None:
        """Neither level alone holds the 10. The bug is a lookahead that checks only the
        best level, which cancels the FOK."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=6,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=2,
                price_e2=101,
                total_e1=6,
                client_order_id="A-2",
            )
        )
        fok_buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=3,
            price_e2=101,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
            order_type=OrderType.FOK,
        )

        events = match(fok_buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=6,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=3,
                    taker_remaining_e1=4,
                ),
                Trade(
                    trade_id=2,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=101,
                    quantity_e1=4,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-2"),
                    maker_exchange_order_id=2,
                    maker_remaining_e1=2,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=3,
                    taker_remaining_e1=0,
                ),
            ],
        )

    def test_a_fok_for_exactly_what_rests_within_its_price_fills_completely(
        self,
    ) -> None:
        """The book holds exactly the 10 the FOK asks for. The bug is a lookahead that
        wants more than 10, which cancels the FOK."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=6,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=2,
                price_e2=101,
                total_e1=4,
                client_order_id="A-2",
            )
        )
        fok_buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=3,
            price_e2=101,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
            order_type=OrderType.FOK,
        )

        events = match(fok_buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=6,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=3,
                    taker_remaining_e1=4,
                ),
                Trade(
                    trade_id=2,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=101,
                    quantity_e1=4,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-2"),
                    maker_exchange_order_id=2,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=3,
                    taker_remaining_e1=0,
                ),
            ],
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
            bids
            """),
        )


def book_with_three_asks() -> Book:
    """A's asks: 6 at 100, 4 at 101 and 5 at 102."""
    book = Book()
    book.add(
        resting_order(
            A,
            Side.SELL,
            exchange_order_id=1,
            price_e2=100,
            total_e1=6,
            client_order_id="A-1",
        )
    )
    book.add(
        resting_order(
            A,
            Side.SELL,
            exchange_order_id=2,
            price_e2=101,
            total_e1=4,
            client_order_id="A-2",
        )
    )
    book.add(
        resting_order(
            A,
            Side.SELL,
            exchange_order_id=3,
            price_e2=102,
            total_e1=5,
            client_order_id="A-3",
        )
    )
    return book


def fok_buy(*, price_e2: Price, total_e1: Quantity) -> IncomingOrder:
    """B's FOK buy, for `_is_completely_fillable`."""
    return incoming_order(
        B,
        Side.BUY,
        exchange_order_id=4,
        price_e2=price_e2,
        total_e1=total_e1,
        request_id=1,
        client_order_id="B-1",
        order_type=OrderType.FOK,
    )


def book_with_three_bids_below_zero() -> Book:
    """A's bids: 6 at -100, 4 at -101 and 5 at -102."""
    book = Book()
    book.add(
        resting_order(
            A,
            Side.BUY,
            exchange_order_id=1,
            price_e2=-100,
            total_e1=6,
            client_order_id="A-1",
        )
    )
    book.add(
        resting_order(
            A,
            Side.BUY,
            exchange_order_id=2,
            price_e2=-101,
            total_e1=4,
            client_order_id="A-2",
        )
    )
    book.add(
        resting_order(
            A,
            Side.BUY,
            exchange_order_id=3,
            price_e2=-102,
            total_e1=5,
            client_order_id="A-3",
        )
    )
    return book


def fok_sell(*, price_e2: Price, total_e1: Quantity) -> IncomingOrder:
    """B's FOK sell, for `_is_completely_fillable`."""
    return incoming_order(
        B,
        Side.SELL,
        exchange_order_id=4,
        price_e2=price_e2,
        total_e1=total_e1,
        request_id=1,
        client_order_id="B-1",
        order_type=OrderType.FOK,
    )
