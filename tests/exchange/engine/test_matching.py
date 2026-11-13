"""matching.py: limit, market and IOC orders, cancels and modifies, meeting a real
book."""

from textwrap import dedent

import pytest

from exchange.engine.book import Book
from exchange.engine.matching import IncomingOrder, _would_cross, cancel, match, modify
from exchange.events import (
    OrderCancelledFromBook,
    OrderCancelledInMatching,
    OrderModifiedLosingPriority,
    OrderModifiedRetainingPriority,
    OrderRested,
    Trade,
)
from helpers.assertions import assert_events, assert_ladder
from helpers.book import resting_order
from helpers.instruments import INSTRUMENT_ID
from helpers.matching import TradeIdCounter, incoming_modify, incoming_order
from helpers.participants import A, B, make_client_order_id
from helpers.times import SEQUENCED_WALL_CLOCK_NS
from protocol.types import OrderType, Price, Quantity, ReasonCode, Side

# The tests are grouped in a class per function, and a function's class comes before
# the classes of the functions that call it. A failure's header names its class, so
# it says which function to look at; and with the order, the first failure is usually
# the one to fix first. The classes hold nothing but the tests.


class Test_would_cross:
    @pytest.mark.parametrize(
        "ask_price_e2", [100, 99], ids=["at its price", "below it"]
    )
    def test_a_buy_crosses_an_ask_at_or_below_its_price(
        self, ask_price_e2: Price
    ) -> None:
        buy = buy_at(100)

        assert _would_cross(buy, ask_price_e2), (
            f"a buy at 100 pays at most 100, so it crosses an ask at {ask_price_e2}"
        )

    def test_a_buy_does_not_cross_an_ask_above_its_price(self) -> None:
        buy = buy_at(100)

        assert not _would_cross(buy, 101), (
            "a buy at 100 pays at most 100, so it does not cross an ask at 101"
        )

    @pytest.mark.parametrize(
        "bid_price_e2", [100, 101], ids=["at its price", "above it"]
    )
    def test_a_sell_crosses_a_bid_at_or_above_its_price(
        self, bid_price_e2: Price
    ) -> None:
        sell = sell_at(100)

        assert _would_cross(sell, bid_price_e2), (
            "a sell at 100 receives at least 100, so it crosses a bid at "
            f"{bid_price_e2}"
        )

    def test_a_sell_does_not_cross_a_bid_below_its_price(self) -> None:
        sell = sell_at(100)

        assert not _would_cross(sell, 99), (
            "a sell at 100 receives at least 100, so it does not cross a bid at 99"
        )

    def test_crossing_is_the_same_rule_at_negative_prices(self) -> None:
        """Power prices can be negative. The bug is comparing how big the prices are,
        ignoring the sign, instead of the prices themselves."""
        sell = sell_at(-800)

        assert _would_cross(sell, -500), (
            "a sell at -800 receives at least -800, so it crosses a bid at -500"
        )
        assert not _would_cross(sell, -1000), (
            "a sell at -800 receives at least -800, so it does not cross a bid at -1000"
        )


class Test_match:
    def test_a_limit_order_into_an_empty_book_rests_whole(self) -> None:
        """There is nothing to trade with, so the order rests whole. The bug is
        cancelling it because nothing crossed: only a market order, an IOC or a FOK is
        cancelled for that."""
        book = Book()
        buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=1,
            price_e2=100,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
        )

        events = match(buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                OrderRested(
                    participant_id=B,
                    exchange_order_id=1,
                    instrument_id=INSTRUMENT_ID,
                    side=Side.BUY,
                    price_e2=100,
                    remaining_e1=10,
                    queue_ahead_quantity_e1=0,
                ),
            ],
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
            bids
              100: #1 (p2) 10
            """),
        )

    def test_the_maker_sets_the_price_for_a_buy_aggressor(self) -> None:
        """A buy at 105 into an ask at 100 trades at 100. The bug is trading at the
        buy's own price, which a test with equal prices cannot catch."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                client_order_id="A-1",
            )
        )
        buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=2,
            price_e2=105,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
        )

        events = match(buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=10,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=2,
                    taker_remaining_e1=0,
                ),
            ],
        )

    def test_the_maker_sets_the_price_for_a_sell_aggressor(self) -> None:
        """The other way round: a sell at 95 into a bid at 100 trades at 100. The bug is
        trading at `min(buy, sell)`, which gives 95."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.BUY,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                client_order_id="A-1",
            )
        )
        sell = incoming_order(
            B,
            Side.SELL,
            exchange_order_id=2,
            price_e2=95,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
        )

        events = match(sell, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=10,
                    aggressor_side=Side.SELL,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=2,
                    taker_remaining_e1=0,
                ),
            ],
        )

    def test_an_aggressor_that_exactly_consumes_the_book_rests_nothing(self) -> None:
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                client_order_id="A-1",
            )
        )
        buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=2,
            price_e2=100,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
        )

        events = match(buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=10,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=2,
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

    def test_a_partially_filled_resting_order_keeps_its_queue_position(self) -> None:
        """The bug is filling the front order by removing it and adding it back, which
        sends it behind order 2."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=2,
                price_e2=100,
                total_e1=10,
                client_order_id="A-2",
            )
        )
        trade_ids = TradeIdCounter()
        first_buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=3,
            price_e2=100,
            total_e1=4,
            request_id=1,
            client_order_id="B-1",
        )
        second_buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=4,
            price_e2=100,
            total_e1=6,
            request_id=2,
            client_order_id="B-2",
        )

        match(first_buy, book, take_trade_id=trade_ids.take_trade_id)
        events = match(second_buy, book, take_trade_id=trade_ids.take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=2,
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
                    taker_client_order_id=make_client_order_id("B-2"),
                    taker_exchange_order_id=4,
                    taker_remaining_e1=0,
                ),
            ],
        )

    def test_at_one_price_an_order_trades_with_each_resting_order_in_turn(self) -> None:
        """A buy of 7 meets 4 and then 6 resting at 100. Two bugs: one trade for both
        resting orders, or trading with the back of the queue first."""
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
                price_e2=100,
                total_e1=6,
                client_order_id="A-2",
            )
        )
        buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=3,
            price_e2=100,
            total_e1=7,
            request_id=1,
            client_order_id="B-1",
        )

        events = match(buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=4,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=3,
                    taker_remaining_e1=3,
                ),
                Trade(
                    trade_id=2,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=3,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-2"),
                    maker_exchange_order_id=2,
                    maker_remaining_e1=3,
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
              100: #2 (p1) 3
            bids
            """),
        )

    def test_a_sweep_trades_each_level_at_its_own_price(self) -> None:
        """A buy of 15 at 102 makes one trade with each resting order, best first: 5 at
        100, 5 at 101 and 5 at 102. The bug is filling the whole sweep at the first or
        the last price."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=5,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=2,
                price_e2=101,
                total_e1=5,
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
        buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=4,
            price_e2=102,
            total_e1=15,
            request_id=1,
            client_order_id="B-1",
        )

        events = match(buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=5,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=4,
                    taker_remaining_e1=10,
                ),
                Trade(
                    trade_id=2,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=101,
                    quantity_e1=5,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-2"),
                    maker_exchange_order_id=2,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=4,
                    taker_remaining_e1=5,
                ),
                Trade(
                    trade_id=3,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=102,
                    quantity_e1=5,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-3"),
                    maker_exchange_order_id=3,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=4,
                    taker_remaining_e1=0,
                ),
            ],
        )

    def test_a_sell_trades_down_the_bids_at_negative_prices_and_rests_the_rest(
        self,
    ) -> None:
        """Power's prices go negative. The bug is a sell branch of the price check that
        accepts whatever bid it meets, which every buy-side test misses."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.BUY,
                exchange_order_id=1,
                price_e2=-500,
                total_e1=5,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                A,
                Side.BUY,
                exchange_order_id=2,
                price_e2=-1000,
                total_e1=5,
                client_order_id="A-2",
            )
        )
        sell = incoming_order(
            B,
            Side.SELL,
            exchange_order_id=3,
            price_e2=-800,
            total_e1=8,
            request_id=1,
            client_order_id="B-1",
        )

        events = match(sell, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=-500,
                    quantity_e1=5,
                    aggressor_side=Side.SELL,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=3,
                    taker_remaining_e1=3,
                ),
                OrderRested(
                    participant_id=B,
                    exchange_order_id=3,
                    instrument_id=INSTRUMENT_ID,
                    side=Side.SELL,
                    price_e2=-800,
                    remaining_e1=3,
                    queue_ahead_quantity_e1=0,
                ),
            ],
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              -800: #3 (p2) 3
            bids
              -1000: #2 (p1) 5
            """),
        )

    def test_what_a_limit_order_cannot_fill_rests(self) -> None:
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
        buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=2,
            price_e2=100,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
        )

        events = match(buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=4,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=2,
                    taker_remaining_e1=6,
                ),
                OrderRested(
                    participant_id=B,
                    exchange_order_id=2,
                    instrument_id=INSTRUMENT_ID,
                    side=Side.BUY,
                    price_e2=100,
                    remaining_e1=6,
                    queue_ahead_quantity_e1=0,
                ),
            ],
        )
        assert book.get_order(2) == resting_order(
            B,
            Side.BUY,
            exchange_order_id=2,
            price_e2=100,
            total_e1=10,
            remaining_e1=6,
            client_order_id="B-1",
        ), (
            f"order 2 should rest with a total of 10, of which 6 are left:\n"
            f"{book.render_state()}"
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
            bids
              100: #2 (p2) 6
            """),
        )

    def test_a_limit_order_that_does_not_cross_rests_behind_the_orders_at_its_price(
        self,
    ) -> None:
        book = Book()
        book.add(
            resting_order(
                A,
                Side.BUY,
                exchange_order_id=1,
                price_e2=100,
                total_e1=5,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=2,
                price_e2=102,
                total_e1=4,
                client_order_id="A-2",
            )
        )
        buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=3,
            price_e2=100,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
        )

        events = match(buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                OrderRested(
                    participant_id=B,
                    exchange_order_id=3,
                    instrument_id=INSTRUMENT_ID,
                    side=Side.BUY,
                    price_e2=100,
                    remaining_e1=10,
                    queue_ahead_quantity_e1=5,
                ),
            ],
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              102: #2 (p1) 4
            bids
              100: #1 (p1) 5, #3 (p2) 10
            """),
        )

    def test_a_market_order_into_an_empty_book_is_cancelled(self) -> None:
        market_buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=1,
            price_e2=110,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
            order_type=OrderType.MARKET,
        )

        events = match(market_buy, Book(), take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                OrderCancelledInMatching(
                    participant_id=B,
                    request_id=1,
                    client_order_id=make_client_order_id("B-1"),
                    exchange_order_id=1,
                    instrument_id=INSTRUMENT_ID,
                    cancelled_e1=10,
                    reason_code=ReasonCode.MARKET_REMAINDER,
                ),
            ],
        )

    def test_a_market_order_stops_at_its_protection_price(self) -> None:
        """Ignoring the protection price would sweep the ask at 110."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=5,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=2,
                price_e2=110,
                total_e1=5,
                client_order_id="A-2",
            )
        )
        market_buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=3,
            price_e2=105,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
            order_type=OrderType.MARKET,
        )

        events = match(market_buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=5,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=3,
                    taker_remaining_e1=5,
                ),
                OrderCancelledInMatching(
                    participant_id=B,
                    request_id=1,
                    client_order_id=make_client_order_id("B-1"),
                    exchange_order_id=3,
                    instrument_id=INSTRUMENT_ID,
                    cancelled_e1=5,
                    reason_code=ReasonCode.PRICE_OUTSIDE_COLLAR,
                ),
            ],
        )

    def test_a_market_order_that_empties_the_book_has_the_rest_cancelled_as_a_market_remainder(
        self,
    ) -> None:
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=5,
                client_order_id="A-1",
            )
        )
        market_buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=2,
            price_e2=110,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
            order_type=OrderType.MARKET,
        )

        events = match(market_buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=5,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=2,
                    taker_remaining_e1=5,
                ),
                OrderCancelledInMatching(
                    participant_id=B,
                    request_id=1,
                    client_order_id=make_client_order_id("B-1"),
                    exchange_order_id=2,
                    instrument_id=INSTRUMENT_ID,
                    cancelled_e1=5,
                    reason_code=ReasonCode.MARKET_REMAINDER,
                ),
            ],
        )

    def test_an_ioc_cancels_what_it_could_not_fill(self) -> None:
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=3,
                client_order_id="A-1",
            )
        )
        ioc_buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=2,
            price_e2=100,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
            order_type=OrderType.IOC,
        )

        events = match(ioc_buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=3,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=2,
                    taker_remaining_e1=7,
                ),
                OrderCancelledInMatching(
                    participant_id=B,
                    request_id=1,
                    client_order_id=make_client_order_id("B-1"),
                    exchange_order_id=2,
                    instrument_id=INSTRUMENT_ID,
                    cancelled_e1=7,
                    reason_code=ReasonCode.IOC_REMAINDER,
                ),
            ],
        )

    def test_an_ioc_that_cannot_trade_is_cancelled_whole(self) -> None:
        """An IOC never rests. The bug is resting one that has not traded at all, as a
        limit order would."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=5,
                client_order_id="A-1",
            )
        )
        ioc_buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=2,
            price_e2=99,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
            order_type=OrderType.IOC,
        )

        events = match(ioc_buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                OrderCancelledInMatching(
                    participant_id=B,
                    request_id=1,
                    client_order_id=make_client_order_id("B-1"),
                    exchange_order_id=2,
                    instrument_id=INSTRUMENT_ID,
                    cancelled_e1=10,
                    reason_code=ReasonCode.IOC_REMAINDER,
                ),
            ],
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              100: #1 (p1) 5
            bids
            """),
        )

    @pytest.mark.parametrize(
        "order_type",
        [OrderType.IOC, OrderType.MARKET],
        ids=["an IOC", "a market order"],
    )
    def test_an_order_that_fills_completely_gets_nothing_after_its_last_trade(
        self, order_type: OrderType
    ) -> None:
        """The order fills completely, so nothing is left. The bug is adding an
        OrderCancelledInMatching after the last trade whenever an order does not rest:
        here it would cancel nothing."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                client_order_id="A-1",
            )
        )
        buy = incoming_order(
            B,
            Side.BUY,
            exchange_order_id=2,
            price_e2=100,
            total_e1=10,
            request_id=1,
            client_order_id="B-1",
            order_type=order_type,
        )

        events = match(buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=10,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=2,
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

    def test_an_order_trades_with_its_own_participants_resting_order(self) -> None:
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=5,
                client_order_id="A-1",
            )
        )
        buy = incoming_order(
            A,
            Side.BUY,
            exchange_order_id=2,
            price_e2=100,
            total_e1=5,
            request_id=2,
            client_order_id="A-2",
        )

        events = match(buy, book, take_trade_id=TradeIdCounter().take_trade_id)

        assert_events(
            events,
            [
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    quantity_e1=5,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=A,
                    taker_client_order_id=make_client_order_id("A-2"),
                    taker_exchange_order_id=2,
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


class Test_cancel:
    def test_a_cancel_takes_the_order_out_and_reports_what_it_had_left(self) -> None:
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                B,
                Side.SELL,
                exchange_order_id=2,
                price_e2=100,
                total_e1=5,
                client_order_id="B-1",
            )
        )
        book.fill(1, quantity_e1=4)

        order_cancelled = cancel(
            1, book, request_id=3, reason_code=ReasonCode.CANCELLED_BY_PARTICIPANT
        )

        assert_events(
            [order_cancelled],
            [
                OrderCancelledFromBook(
                    participant_id=A,
                    request_id=3,
                    client_order_id=make_client_order_id("A-1"),
                    exchange_order_id=1,
                    instrument_id=INSTRUMENT_ID,
                    cancelled_e1=6,
                    reason_code=ReasonCode.CANCELLED_BY_PARTICIPANT,
                ),
            ],
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              100: #2 (p2) 5
            bids
            """),
        )


class Test_modify:
    def test_a_modify_that_shrinks_an_order_keeps_its_queue_position(self) -> None:
        """The order has a total of 10, of which 4 have filled, so 6 are left. A new
        total of 8 leaves 4. The bug is reading the 8 as what is left: that would grow
        the order from 6 to 8 and send it to the back."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                remaining_e1=6,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                B,
                Side.SELL,
                exchange_order_id=2,
                price_e2=100,
                total_e1=10,
                client_order_id="B-1",
            )
        )

        events = modify(
            incoming_modify(
                exchange_order_id=1,
                new_price_e2=100,
                new_total_e1=8,
                request_id=3,
            ),
            book,
            take_trade_id=TradeIdCounter().take_trade_id,
        )

        assert_events(
            events,
            [
                OrderModifiedRetainingPriority(
                    participant_id=A,
                    request_id=3,
                    client_order_id=make_client_order_id("A-1"),
                    exchange_order_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    total_e1=8,
                    remaining_e1=4,
                ),
            ],
        )
        assert book.get_order(1) == resting_order(
            A,
            Side.SELL,
            exchange_order_id=1,
            price_e2=100,
            total_e1=8,
            remaining_e1=4,
            client_order_id="A-1",
        ), (
            f"order 1 should rest with a total of 8, of which 4 are left:\n"
            f"{book.render_state()}"
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              100: #1 (p1) 4, #2 (p2) 10
            bids
            """),
        )

    def test_a_modify_that_changes_nothing_keeps_its_queue_position(self) -> None:
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                remaining_e1=6,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                B,
                Side.SELL,
                exchange_order_id=2,
                price_e2=100,
                total_e1=10,
                client_order_id="B-1",
            )
        )

        events = modify(
            incoming_modify(
                exchange_order_id=1,
                new_price_e2=100,
                new_total_e1=10,
                request_id=3,
            ),
            book,
            take_trade_id=TradeIdCounter().take_trade_id,
        )

        assert_events(
            events,
            [
                OrderModifiedRetainingPriority(
                    participant_id=A,
                    request_id=3,
                    client_order_id=make_client_order_id("A-1"),
                    exchange_order_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    total_e1=10,
                    remaining_e1=6,
                ),
            ],
        )
        assert book.get_order(1) == resting_order(
            A,
            Side.SELL,
            exchange_order_id=1,
            price_e2=100,
            total_e1=10,
            remaining_e1=6,
            client_order_id="A-1",
        ), (
            f"order 1 should rest with a total of 10, of which 6 are left:\n"
            f"{book.render_state()}"
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              100: #1 (p1) 6, #2 (p2) 10
            bids
            """),
        )

    def test_a_modify_that_grows_an_order_sends_it_to_the_back(self) -> None:
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                remaining_e1=6,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                B,
                Side.SELL,
                exchange_order_id=2,
                price_e2=100,
                total_e1=10,
                client_order_id="B-1",
            )
        )

        events = modify(
            incoming_modify(
                exchange_order_id=1,
                new_price_e2=100,
                new_total_e1=12,
                request_id=3,
            ),
            book,
            take_trade_id=TradeIdCounter().take_trade_id,
        )

        assert_events(
            events,
            [
                OrderModifiedLosingPriority(
                    participant_id=A,
                    request_id=3,
                    client_order_id=make_client_order_id("A-1"),
                    exchange_order_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    total_e1=12,
                ),
                OrderRested(
                    participant_id=A,
                    exchange_order_id=1,
                    instrument_id=INSTRUMENT_ID,
                    side=Side.SELL,
                    price_e2=100,
                    remaining_e1=8,
                    queue_ahead_quantity_e1=10,
                ),
            ],
        )
        assert book.get_order(1) == resting_order(
            A,
            Side.SELL,
            exchange_order_id=1,
            price_e2=100,
            total_e1=12,
            remaining_e1=8,
            client_order_id="A-1",
        ), (
            f"order 1 should rest with a total of 12, of which 8 are left:\n"
            f"{book.render_state()}"
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              100: #2 (p2) 10, #1 (p1) 8
            bids
            """),
        )

    def test_a_modify_to_a_new_price_sends_it_to_the_back_there(self) -> None:
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                remaining_e1=6,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                B,
                Side.SELL,
                exchange_order_id=2,
                price_e2=101,
                total_e1=10,
                client_order_id="B-1",
            )
        )

        events = modify(
            incoming_modify(
                exchange_order_id=1,
                new_price_e2=101,
                new_total_e1=10,
                request_id=3,
            ),
            book,
            take_trade_id=TradeIdCounter().take_trade_id,
        )

        assert_events(
            events,
            [
                OrderModifiedLosingPriority(
                    participant_id=A,
                    request_id=3,
                    client_order_id=make_client_order_id("A-1"),
                    exchange_order_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=101,
                    total_e1=10,
                ),
                OrderRested(
                    participant_id=A,
                    exchange_order_id=1,
                    instrument_id=INSTRUMENT_ID,
                    side=Side.SELL,
                    price_e2=101,
                    remaining_e1=6,
                    queue_ahead_quantity_e1=10,
                ),
            ],
        )
        assert book.get_order(1) == resting_order(
            A,
            Side.SELL,
            exchange_order_id=1,
            price_e2=101,
            total_e1=10,
            remaining_e1=6,
            client_order_id="A-1",
        ), (
            f"order 1 should rest with a total of 10, of which 6 are left:\n"
            f"{book.render_state()}"
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              101: #2 (p2) 10, #1 (p1) 6
            bids
            """),
        )

    def test_a_modify_whose_new_price_crosses_trades_before_it_rests(self) -> None:
        """B's bid at 100 is modified to 101, which crosses A's ask at 101. The bug is
        re-pricing the bid in place, without matching."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=101,
                total_e1=10,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                B,
                Side.BUY,
                exchange_order_id=2,
                price_e2=100,
                total_e1=15,
                client_order_id="B-1",
            )
        )

        events = modify(
            incoming_modify(
                exchange_order_id=2,
                new_price_e2=101,
                new_total_e1=15,
                request_id=3,
            ),
            book,
            take_trade_id=TradeIdCounter().take_trade_id,
        )

        assert_events(
            events,
            [
                OrderModifiedLosingPriority(
                    participant_id=B,
                    request_id=3,
                    client_order_id=make_client_order_id("B-1"),
                    exchange_order_id=2,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=101,
                    total_e1=15,
                ),
                Trade(
                    trade_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=101,
                    quantity_e1=10,
                    aggressor_side=Side.BUY,
                    trade_wall_clock_ns=SEQUENCED_WALL_CLOCK_NS,
                    maker_participant_id=A,
                    maker_client_order_id=make_client_order_id("A-1"),
                    maker_exchange_order_id=1,
                    maker_remaining_e1=0,
                    taker_participant_id=B,
                    taker_client_order_id=make_client_order_id("B-1"),
                    taker_exchange_order_id=2,
                    taker_remaining_e1=5,
                ),
                OrderRested(
                    participant_id=B,
                    exchange_order_id=2,
                    instrument_id=INSTRUMENT_ID,
                    side=Side.BUY,
                    price_e2=101,
                    remaining_e1=5,
                    queue_ahead_quantity_e1=0,
                ),
            ],
        )
        assert book.get_order(2) == resting_order(
            B,
            Side.BUY,
            exchange_order_id=2,
            price_e2=101,
            total_e1=15,
            remaining_e1=5,
            client_order_id="B-1",
        ), (
            f"order 2 should rest with a total of 15, of which 5 are left:\n"
            f"{book.render_state()}"
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
            bids
              101: #2 (p2) 5
            """),
        )

    @pytest.mark.parametrize(
        "new_total_e1", [4, 3], ids=["at what has filled", "below it"]
    )
    def test_a_modify_to_no_more_than_has_filled_cancels_the_rest(
        self, new_total_e1: Quantity
    ) -> None:
        """Order 1 has a total of 10, of which 4 have filled, so 6 are left. A new total
        of 4 or less cancels those 6. Two bugs: cancelling only when the new total is
        below 4, which lets a new total of 4 through with nothing left to trade; or
        cancelling only when it is exactly 4, which lets 3 through, leaving -1 to
        trade."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                remaining_e1=6,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                B,
                Side.SELL,
                exchange_order_id=2,
                price_e2=100,
                total_e1=10,
                client_order_id="B-1",
            )
        )

        events = modify(
            incoming_modify(
                exchange_order_id=1,
                new_price_e2=100,
                new_total_e1=new_total_e1,
                request_id=3,
            ),
            book,
            take_trade_id=TradeIdCounter().take_trade_id,
        )

        assert_events(
            events,
            [
                OrderCancelledFromBook(
                    participant_id=A,
                    request_id=3,
                    client_order_id=make_client_order_id("A-1"),
                    exchange_order_id=1,
                    instrument_id=INSTRUMENT_ID,
                    cancelled_e1=6,
                    reason_code=ReasonCode.MODIFY_BELOW_FILLED,
                ),
            ],
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              100: #2 (p2) 10
            bids
            """),
        )

    def test_a_modify_counts_what_has_filled_toward_its_new_total(self) -> None:
        """Order 1 has a total of 10, of which 4 have filled, so 6 are left. The
        participant asks for a new total of 5, which leaves 1. Two bugs: comparing the 5
        with the 6 that are left instead of the 4 that have filled, which cancels the
        order; or reading the 5 as what is left, which the book's `amend` refuses, since
        a total of 5 with 5 left would change what has filled."""
        book = Book()
        book.add(
            resting_order(
                A,
                Side.SELL,
                exchange_order_id=1,
                price_e2=100,
                total_e1=10,
                remaining_e1=6,
                client_order_id="A-1",
            )
        )
        book.add(
            resting_order(
                B,
                Side.SELL,
                exchange_order_id=2,
                price_e2=100,
                total_e1=10,
                client_order_id="B-1",
            )
        )

        events = modify(
            incoming_modify(
                exchange_order_id=1,
                new_price_e2=100,
                new_total_e1=5,
                request_id=3,
            ),
            book,
            take_trade_id=TradeIdCounter().take_trade_id,
        )

        assert_events(
            events,
            [
                OrderModifiedRetainingPriority(
                    participant_id=A,
                    request_id=3,
                    client_order_id=make_client_order_id("A-1"),
                    exchange_order_id=1,
                    instrument_id=INSTRUMENT_ID,
                    price_e2=100,
                    total_e1=5,
                    remaining_e1=1,
                ),
            ],
        )
        assert book.get_order(1) == resting_order(
            A,
            Side.SELL,
            exchange_order_id=1,
            price_e2=100,
            total_e1=5,
            remaining_e1=1,
            client_order_id="A-1",
        ), (
            f"order 1 should rest with a total of 5, of which 1 is left:\n"
            f"{book.render_state()}"
        )
        assert_ladder(
            book.render_state(),
            dedent("""\
            price_e2: #exchange_order_id (p participant_id) remaining_e1, queue front first
            asks
              100: #1 (p1) 1, #2 (p2) 10
            bids
            """),
        )


def buy_at(price_e2: Price) -> IncomingOrder:
    """A buy of 10 for `_would_cross`, which reads only its side and its price."""
    return incoming_order(
        B,
        Side.BUY,
        exchange_order_id=1,
        price_e2=price_e2,
        total_e1=10,
        request_id=1,
        client_order_id="B-1",
    )


def sell_at(price_e2: Price) -> IncomingOrder:
    """A sell of 10, as `buy_at`."""
    return incoming_order(
        B,
        Side.SELL,
        exchange_order_id=1,
        price_e2=price_e2,
        total_e1=10,
        request_id=1,
        client_order_id="B-1",
    )
