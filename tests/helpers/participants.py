"""The two participants every test trades as, and the ids they give their orders."""

from protocol.types import (
    CLIENT_ORDER_ID_CHARACTERS,
    MAX_CLIENT_ORDER_ID_BYTES,
    ClientOrderId,
    ParticipantId,
)

A: ParticipantId = 1
B: ParticipantId = 2


def make_client_order_id(text: str) -> ClientOrderId:
    """`text` as a client order id: `"A-1"` becomes `b"A-1"`. Raises ValueError if no
    valid order could carry `text` as its id; a test about an invalid id writes its
    bytes out instead.
    """
    if text == "":
        raise ValueError("a client order id has at least one character, not none")
    valid_characters = CLIENT_ORDER_ID_CHARACTERS.decode("ascii")
    invalid_characters = [
        character for character in text if character not in valid_characters
    ]
    if invalid_characters:
        raise ValueError(
            f"a client order id has only letters, digits, '_' and '-'; {text!r} has "
            f"{invalid_characters}"
        )
    client_order_id = text.encode("ascii")
    if len(client_order_id) > MAX_CLIENT_ORDER_ID_BYTES:
        raise ValueError(
            f"a client order id is at most {MAX_CLIENT_ORDER_ID_BYTES} bytes; "
            f"{text!r} has {len(client_order_id)}"
        )
    return client_order_id
