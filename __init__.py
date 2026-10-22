"""
Anki Dock/Taskbar Badge Add-on (fork of DroidThug/ankibadge)
Shows total due cards (New + Learning + Review) as a badge on the app icon.

On macOS the badge is set through UNUserNotificationCenter instead of the Dock
tile, so the last number stays on the Anki icon after Anki quits. Other
platforms (and any macOS failure) use Qt 6.5+ QGuiApplication.setBadgeNumber().
"""

import ctypes
import ctypes.util
import logging
import sys

from aqt import mw, gui_hooks
from aqt.qt import QGuiApplication

log = logging.getLogger(__name__)

_app = QGuiApplication.instance()
_can_set_badge = _app is not None and hasattr(_app, "setBadgeNumber")  # Qt 6.5+


class _MacBadge:
    """Minimal ctypes bridge to UNUserNotificationCenter (no PyObjC in Anki)."""

    class _Desc(ctypes.Structure):
        _fields_ = [("reserved", ctypes.c_ulong), ("size", ctypes.c_ulong)]

    class _Block(ctypes.Structure):
        _fields_ = [("isa", ctypes.c_void_p), ("flags", ctypes.c_int), ("reserved", ctypes.c_int),
                    ("invoke", ctypes.c_void_p), ("desc", ctypes.c_void_p)]

    def __init__(self) -> None:
        self._objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/UserNotifications.framework/UserNotifications"
        )
        libsys = ctypes.CDLL(ctypes.util.find_library("System"))
        o = self._objc
        o.objc_getClass.restype = ctypes.c_void_p
        o.objc_getClass.argtypes = [ctypes.c_char_p]
        o.sel_registerName.restype = ctypes.c_void_p
        o.sel_registerName.argtypes = [ctypes.c_char_p]
        self._isa = ctypes.c_void_p.in_dll(libsys, "_NSConcreteGlobalBlock").value
        # One reusable completion block per signature; kept alive for the session.
        self._auth_block = self._block(ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_bool, ctypes.c_void_p), self._on_auth)
        self._done_block = self._block(ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p), self._on_done)

    def _block(self, cfunc_type, py):
        fn = cfunc_type(py)
        desc = self._Desc(0, ctypes.sizeof(self._Block))
        blk = self._Block(self._isa, 1 << 28, 0, ctypes.cast(fn, ctypes.c_void_p).value, ctypes.addressof(desc))
        self._refs = getattr(self, "_refs", []) + [(fn, desc, blk)]
        return ctypes.addressof(blk)

    @staticmethod
    def _on_auth(_blk, granted, err) -> None:
        if not granted:
            log.warning("ankibadge: notification badge permission not granted (err=%s)", err)

    @staticmethod
    def _on_done(_blk, err) -> None:
        if err:
            log.warning("ankibadge: setBadgeCount failed (err=%s)", err)

    def _msg(self, obj, sel, argtypes=(), args=(), restype=ctypes.c_void_p):
        send = self._objc.objc_msgSend
        send.restype = restype
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return send(obj, self._objc.sel_registerName(sel.encode()), *args)

    def _center(self):
        return self._msg(self._objc.objc_getClass(b"UNUserNotificationCenter"), "currentNotificationCenter")

    def request_auth(self) -> None:
        # UNAuthorizationOptionBadge = 1; only prompts the first time.
        self._msg(self._center(), "requestAuthorizationWithOptions:completionHandler:",
                  (ctypes.c_ulong, ctypes.c_void_p), (1, self._auth_block), restype=None)

    def set(self, n: int) -> None:
        self._msg(self._center(), "setBadgeCount:withCompletionHandler:",
                  (ctypes.c_long, ctypes.c_void_p), (n, self._done_block), restype=None)


_mac = None
if sys.platform == "darwin":
    try:
        _mac = _MacBadge()
        _mac.request_auth()
    except Exception as e:
        log.warning("ankibadge: macOS persistent badge unavailable, using Qt: %s", e)
        _mac = None


def _get_due_count() -> int:
    if mw.col is None:
        return 0
    tree = mw.col.sched.deck_due_tree()
    return tree.new_count + tree.learn_count + tree.review_count


def update_badge() -> None:
    try:
        n = _get_due_count()
        if _mac is not None:
            _mac.set(n)  # 0 clears it
        elif _can_set_badge:
            _app.setBadgeNumber(n)
    except Exception as e:
        log.warning("ankibadge: failed to update badge: %s", e)


def _on_change(changes, _handler) -> None:
    if changes.study_queues:
        update_badge()

gui_hooks.main_window_did_init.append(update_badge)
gui_hooks.collection_did_load.append(lambda _col: update_badge())  # first paint
gui_hooks.operation_did_execute.append(_on_change)                 # everything after
