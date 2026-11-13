"""Real UDP multicast between two processes works inside the course container.

This is the reason the container exists. The venue's market-data feed is
multicast: one process sends each update once and every listener receives it. That
only works reliably when sender and listeners share one machine's network, which the
container gives us.

Multicast has an unpleasant way of failing: if the sender and the listener use
different network interfaces, the send succeeds, nothing arrives, and no error
appears anywhere. So both ends here name the interface explicitly.

The test runs only inside the container, which sets HOMEWORK_MULTICAST=1 to promise
that multicast works there. Outside it, the test is skipped rather than failed.
"""

import fcntl
import os
import random
import socket
import struct
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("HOMEWORK_MULTICAST"),
    reason="real multicast is only guaranteed inside the course container "
    "(HOMEWORK_MULTICAST is not set)",
)

# Flags from <linux/if.h>, as found in /sys/class/net/<interface>/flags.
IFF_UP = 0x1
IFF_LOOPBACK = 0x8
IFF_MULTICAST = 0x1000
# The ioctl that asks the kernel for an interface's IPv4 address, and where its reply
# holds it: after the interface's name field and the address's family and port.
SIOCGIFADDR = 0x8915
MAX_INTERFACE_NAME_LENGTH_IN_BYTES = 15
INTERFACE_NAME_FIELD_SIZE_IN_BYTES = 16
IPV4_ADDRESS_OFFSET = INTERFACE_NAME_FIELD_SIZE_IN_BYTES + 4
IPV4_ADDRESS_SIZE_IN_BYTES = 4

# The listener, run as a second Python process.
LISTENER_SCRIPT = textwrap.dedent(
    """
    import socket, sys

    group, interface_address = sys.argv[1], sys.argv[2]
    multicast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    multicast_socket.bind(("", 0))  # any free port; the sender is told which one
    multicast_socket.setsockopt(
        socket.IPPROTO_IP,
        socket.IP_ADD_MEMBERSHIP,
        socket.inet_aton(group) + socket.inet_aton(interface_address),
    )
    multicast_socket.settimeout(5)
    print(multicast_socket.getsockname()[1], flush=True)
    message, _ = multicast_socket.recvfrom(1024)
    print(message.decode(), flush=True)
    """
)


def ipv4_address(interface: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe_socket:
        ioctl_request = struct.pack(
            "256s", interface.encode()[:MAX_INTERFACE_NAME_LENGTH_IN_BYTES]
        )
        ioctl_reply = fcntl.ioctl(probe_socket.fileno(), SIOCGIFADDR, ioctl_request)
    return socket.inet_ntoa(
        ioctl_reply[
            IPV4_ADDRESS_OFFSET : IPV4_ADDRESS_OFFSET + IPV4_ADDRESS_SIZE_IN_BYTES
        ]
    )


def multicast_interface_address() -> str:
    """The IPv4 address of the first interface that is up, multicast, not loopback."""
    for _, name in socket.if_nameindex():
        flags = int(Path(f"/sys/class/net/{name}/flags").read_text(), 16)
        if flags & IFF_UP and flags & IFF_MULTICAST and not flags & IFF_LOOPBACK:
            return ipv4_address(name)
    pytest.fail(
        "The container has no network interface that supports multicast. Was it "
        "started with --network none? Use the command in the README, which needs no "
        "network flag."
    )


def test_multicast_reaches_a_listener_in_another_process() -> None:
    interface_address = multicast_interface_address()
    # A fresh group each run, from the range reserved for local use, so two test
    # runs on one machine never hear each other.
    second_octet = random.randrange(256)
    third_octet = random.randrange(256)
    fourth_octet = random.randrange(1, 255)
    group = f"239.{second_octet}.{third_octet}.{fourth_octet}"

    listener_process = subprocess.Popen(
        [sys.executable, "-c", LISTENER_SCRIPT, group, interface_address],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert listener_process.stdout is not None
        port = int(listener_process.stdout.readline())

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sending_socket:
            # Send on the same interface the listener joined on.
            sending_socket.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(interface_address),
            )
            # Deliver our own multicast to listeners on this machine. On by default
            # on Linux; set so the test does not depend on that.
            sending_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            # Never leave this machine.
            sending_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            for _ in range(3):
                sending_socket.sendto(b"hello, feed", (group, port))
                time.sleep(0.1)

        received_text, error_text = listener_process.communicate(timeout=10)
    finally:
        listener_process.kill()

    assert received_text.strip() == "hello, feed", (
        f"Sent to multicast group {group}:{port} on interface {interface_address}, and "
        f"the listener in the other process received nothing.\n"
        f"Multicast fails silently: the send succeeds and nothing arrives. The usual "
        f"cause is the two ends using different network interfaces.\n"
        f"Listener's own report:\n{error_text}"
    )
