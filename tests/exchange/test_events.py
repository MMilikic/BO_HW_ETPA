"""events.py: what the engine can decide, and whom each event names."""

from dataclasses import fields
from typing import Any, get_args

from exchange.events import (
    Event,
    Trade,
)


def test_every_event_but_a_trade_names_the_participant_that_it_concerns() -> None:
    event_classes = [
        event_class for event_class in get_args(Event) if event_class is not Trade
    ]
    class_names_missing = [
        event_class.__name__
        for event_class in event_classes
        if "participant_id" not in field_names(event_class)
    ]

    assert class_names_missing == [], (
        f"{class_names_missing} carry no participant_id; the publisher routes on it"
    )


def test_a_trade_names_both_participants() -> None:
    trade_field_names = field_names(Trade)

    assert "maker_participant_id" in trade_field_names, (
        "the maker's fill is routed on this"
    )
    assert "taker_participant_id" in trade_field_names, (
        "the taker's fill is routed on this"
    )


def test_queue_position_is_carried_by_the_order_rested_event_alone() -> None:
    class_names_carrying = [
        event_class.__name__
        for event_class in get_args(Event)
        if "queue_ahead_quantity_e1" in field_names(event_class)
    ]

    assert class_names_carrying == ["OrderRested"], (
        "queue position belongs to the engine; it must never reach anything that "
        f"becomes a wire message, but {class_names_carrying} carry it"
    )


def field_names(event_class: type[Any]) -> list[str]:
    return [field.name for field in fields(event_class)]
