"""Native window or browser: kigit gui picks its own window on Windows and the
browser elsewhere, and falls back to the browser when a window can't open."""

import sys

from kigit_gui import app


def never():
    raise AssertionError("shouldn't check for a window system")


def test_auto_is_native_on_windows():
    assert app.choose_window("auto", "win32", lambda: None) == (True, None)


def test_auto_is_browser_elsewhere_without_checking():
    assert app.choose_window("auto", "linux", never) == (False, None)


def test_browser_never_checks():
    assert app.choose_window("browser", "win32", never) == (False, None)


def test_native_falls_back_with_the_reason():
    native, why = app.choose_window("native", "linux", lambda: "no GTK or Qt")
    assert not native
    assert why == "no GTK or Qt"


def test_native_works_anywhere_a_window_can_open():
    assert app.choose_window("native", "linux", lambda: None) == (True, None)


def test_missing_pywebview_is_a_reason_not_a_crash(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview", None)  # import webview -> ImportError
    assert app.native_problem() == "pywebview isn't installed"
