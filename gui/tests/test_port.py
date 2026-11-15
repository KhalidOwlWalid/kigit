"""Which port kigit gui serves on: --port, or the default and the next free
ones after it, so several GUIs can run at once."""

import socket

import pytest

from kigit_gui import app


def test_default_when_free() -> None:
    assert app.pick_port(None, free=lambda p: True) == app.DEFAULT_PORT


def test_next_free_when_default_is_taken() -> None:
    taken = {app.DEFAULT_PORT, app.DEFAULT_PORT + 1}
    assert app.pick_port(None, free=lambda p: p not in taken) == app.DEFAULT_PORT + 2


def test_all_taken() -> None:
    with pytest.raises(SystemExit, match="all in use"):
        app.pick_port(None, free=lambda p: False)


def test_chosen_port() -> None:
    assert app.pick_port(9123, free=lambda p: True) == 9123


def test_chosen_port_in_use_is_an_error() -> None:
    """--port is what you asked for: no quiet move to another one."""
    with pytest.raises(SystemExit, match="port 9123 is in use"):
        app.pick_port(9123, free=lambda p: p != 9123)


def test_chosen_port_out_of_range() -> None:
    with pytest.raises(SystemExit, match="between 1 and 65535"):
        app.pick_port(70000, free=lambda p: True)


def test_port_free_sees_a_listening_server() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert not app.port_free(port)
    assert app.port_free(port)  # closed again
