"""The vocabulary every wire message, command and event is built from.

Enums for sides, order types, order states and reasons, and one type alias for each
kind of number and id. Each alias carries its width on the wire as a `struct` code,
so the codec reads a field's encoding from its declaration and nowhere else.

Prices and quantities are fixed-point integers, and every field's name says the
scale: `price_e2` is in hundredths of a euro per MWh and `quantity_e1` in tenths of
a MW. A price times a quantity is `_e3`. One unit is the wire's smallest step, not
the market's: the instrument's tick and lot say which prices and quantities the
venue accepts. XBID's are one unit each. There is one scale for everything, so the
scale lives in the names rather than in configuration.

This module only declares; it decides nothing.
"""

import struct
from enum import IntEnum
from typing import Annotated


class Side(IntEnum):
    BUY = 1
    SELL = 2


class OrderType(IntEnum):
    """How an order meets the book.

    A limit order rests whatever it does not fill. A market order, an IOC and a FOK
    never rest: the market order and the IOC cancel what they could not fill, and a
    FOK fills completely or not at all. Anything that rests stays until it is filled
    or cancelled; there is no other time-in-force.
    """

    LIMIT = 1
    MARKET = 2
    IOC = 3
    FOK = 4


class ReasonCode(IntEnum):
    """Why a request was rejected, an order cancelled, or a kill switch changed.

    One list for the whole venue. The values travel on the wire, so a new reason is
    appended at the end and no value is ever renumbered: a client built before a
    renumbering would read reasons that never happened.
    """

    PRICE_OUTSIDE_COLLAR = 9
    IOC_REMAINDER = 13
    MARKET_REMAINDER = 14
    FOK_UNFILLABLE = 15
    MODIFY_BELOW_FILLED = 16
    CANCELLED_BY_PARTICIPANT = 17


SIGNED_8_BYTES = "q"
UNSIGNED_8_BYTES = "Q"
UNSIGNED_4_BYTES = "I"
UNSIGNED_2_BYTES = "H"
ONE_BYTE = "B"
THIRTY_TWO_RAW_BYTES = "32s"

Price = Annotated[int, SIGNED_8_BYTES]  # power prices go negative
Quantity = Annotated[int, UNSIGNED_4_BYTES]
ExchangeOrderId = Annotated[int, UNSIGNED_8_BYTES]
TradeId = Annotated[int, UNSIGNED_8_BYTES]
ParticipantId = Annotated[int, UNSIGNED_2_BYTES]
InstrumentId = Annotated[int, UNSIGNED_4_BYTES]
Nanos = Annotated[int, UNSIGNED_8_BYTES]
RequestId = Annotated[int, UNSIGNED_4_BYTES]
# 1 to MAX_CLIENT_ORDER_ID_BYTES bytes, each one of CLIENT_ORDER_ID_CHARACTERS; or
# empty, as NO_CLIENT_ORDER_ID.
ClientOrderId = Annotated[bytes, THIRTY_TWO_RAW_BYTES]

# The request_id of a venue-initiated message, which nobody asked for, such as
# cancel-on-disconnect's cancels. A fixed-size field cannot say "none", so 0 stands
# for it, and no participant may send it.
NO_REQUEST_ID: RequestId = 0

# The client_order_id of a request about no one order, such as a mass cancel: the
# empty id, which is thirty-two zero bytes on the wire.
NO_CLIENT_ORDER_ID: ClientOrderId = b""

CLIENT_ORDER_ID_CHARACTERS = (
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)

# Each of CLIENT_ORDER_ID_CHARACTERS is one byte, so the limit in bytes is also the
# limit in characters.
MAX_CLIENT_ORDER_ID_BYTES = struct.calcsize(THIRTY_TWO_RAW_BYTES)
