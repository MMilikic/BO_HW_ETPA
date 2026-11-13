"""Everything that crosses the wire, and nothing else.

The venue and every client share this package: the types, the messages, the codec
that turns them into bytes, and the framing that finds them in a stream. It imports
nothing from `exchange` or `clients`, so a client can speak the protocol without
knowing anything about how the venue works inside.
"""
