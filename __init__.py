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
import time

from aqt import mw, gui_hooks
from aqt.qt import QGuiApplication

from .projection import project_badge_counts

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
        self.done_count = 0
        self.granted = None  # unknown until the permission callback runs
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

    def _on_auth(self, _blk, granted, err) -> None:
        self.granted = bool(granted)
        if not granted:
            log.warning("ankibadge: notification badge permission not granted (err=%s)", err)

    def _on_done(self, _blk, err) -> None:
        self.done_count += 1
        if err:
            log.warning("ankibadge: badge request failed (err=%s)", err)

    def wait_for_acks(self, since: int, expected: int, timeout: float = 3.0) -> None:
        """Block until `expected` completion callbacks arrived after count `since`.
        Requests are sent asynchronously; quitting before they are acknowledged
        can drop them."""
        deadline = time.time() + timeout
        while self.done_count - since < expected and time.time() < deadline:
            time.sleep(0.02)

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

    def clear_pending(self) -> None:
        self._msg(self._center(), "removeAllPendingNotificationRequests", restype=None)

    def schedule(self, n: int, seconds: float, ident: str) -> None:
        """Badge-only local notification (no title/body/sound): macOS applies the
        number at the given time even if Anki is no longer running."""
        string = self._msg(self._objc.objc_getClass(b"NSString"), "stringWithUTF8String:",
                           (ctypes.c_char_p,), (ident.encode(),))
        number = self._msg(self._objc.objc_getClass(b"NSNumber"), "numberWithInt:",
                           (ctypes.c_int,), (n,))
        content = self._msg(self._objc.objc_getClass(b"UNMutableNotificationContent"), "new")
        self._msg(content, "setBadge:", (ctypes.c_void_p,), (number,), restype=None)
        trigger = self._msg(self._objc.objc_getClass(b"UNTimeIntervalNotificationTrigger"),
                            "triggerWithTimeInterval:repeats:", (ctypes.c_double, ctypes.c_bool),
                            (float(seconds), False))
        request = self._msg(self._objc.objc_getClass(b"UNNotificationRequest"),
                            "requestWithIdentifier:content:trigger:",
                            (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p), (string, content, trigger))
        self._msg(self._center(), "addNotificationRequest:withCompletionHandler:",
                  (ctypes.c_void_p, ctypes.c_void_p), (request, self._done_block), restype=None)
        self._msg(content, "release", restype=None)  # created with +new; the center keeps its own reference


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
        if _mac is not None and _mac.granted is not False:
            _mac.set(n)  # 0 clears it
        elif _can_set_badge:
            _app.setBadgeNumber(n)
    except Exception as e:
        log.warning("ankibadge: failed to update badge: %s", e)


def _clear_scheduled() -> None:
    """Drop badge updates queued at the last quit, so a stale number can't fire
    while Anki is open."""
    if _mac is None:
        return
    try:
        _mac.clear_pending()
    except Exception as e:
        log.warning("ankibadge: failed to clear scheduled badge updates: %s", e)


def schedule_for_quit() -> None:
    """Queue the numbers Anki will have in the coming hours, so the badge keeps
    updating while it is closed (learning cards coming due, the day rollover)."""
    if _mac is None or _mac.granted is False or mw.col is None:
        return
    try:
        now = int(time.time())
        _clear_scheduled()
        points = project_badge_counts(mw.col, now)
        sent = _mac.done_count
        for i, (when, n) in enumerate(points):
            _mac.schedule(n, max(5, when - now), f"ankibadge-{i}")
        _mac.wait_for_acks(sent, len(points))
    except Exception as e:
        log.warning("ankibadge: failed to schedule badge updates: %s", e)


def _on_change(changes, _handler) -> None:
    if changes.study_queues:
        update_badge()


def _on_collection_loaded(_col) -> None:
    _clear_scheduled()
    update_badge()  # first paint


gui_hooks.main_window_did_init.append(update_badge)
gui_hooks.collection_did_load.append(_on_collection_loaded)
gui_hooks.operation_did_execute.append(_on_change)                 # everything after
gui_hooks.profile_will_close.append(schedule_for_quit)
