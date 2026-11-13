"""The times every command carries: when it was received, and when it was sequenced."""

from protocol.types import Nanos

RECEIVED_WALL_CLOCK_NS: Nanos = 1_000_000
# Different from RECEIVED_WALL_CLOCK_NS, so a test catches code that uses the received
# time where the sequenced time belongs.
SEQUENCED_WALL_CLOCK_NS: Nanos = 2_000_000
