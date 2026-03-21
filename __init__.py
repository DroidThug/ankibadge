"""
Anki macOS Dock Badge Add-on

Displays the total number of due cards (New + Learning + Review)
as a numeric badge on the macOS Dock icon.
"""

import sys
import logging
import ctypes
import ctypes.util

log = logging.getLogger(__name__)

_can_set_badge = False

if sys.platform == "darwin":
    try:
        from AppKit import NSApplication

        def _set_dock_badge(label: str) -> None:
            NSApplication.sharedApplication().dockTile().setBadgeLabel_(label)

        _can_set_badge = True
        print("ankibadge: using AppKit backend")
    except ImportError:
        print("ankibadge: AppKit not available, trying ctypes fallback")
        try:
            objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))

            objc.objc_getClass.restype = ctypes.c_void_p
            objc.objc_getClass.argtypes = [ctypes.c_char_p]
            objc.sel_registerName.restype = ctypes.c_void_p
            objc.sel_registerName.argtypes = [ctypes.c_char_p]
            objc.objc_msgSend.restype = ctypes.c_void_p
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

            NSString = objc.objc_getClass(b"NSString")
            sel_shared = objc.sel_registerName(b"sharedApplication")
            sel_dock = objc.sel_registerName(b"dockTile")
            sel_set_badge = objc.sel_registerName(b"setBadgeLabel:")
            sel_string = objc.sel_registerName(b"stringWithUTF8String:")

            def _nsstring(s: str) -> ctypes.c_void_p:
                objc.objc_msgSend.argtypes = [
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p
                ]
                objc.objc_msgSend.restype = ctypes.c_void_p
                return objc.objc_msgSend(NSString, sel_string, s.encode("utf-8"))

            def _set_dock_badge(label: str) -> None:
                objc.objc_msgSend.argtypes = [
                    ctypes.c_void_p, ctypes.c_void_p
                ]
                objc.objc_msgSend.restype = ctypes.c_void_p
                NSApp = objc.objc_getClass(b"NSApplication")
                app = objc.objc_msgSend(NSApp, sel_shared)
                dock = objc.objc_msgSend(app, sel_dock)
                ns_label = _nsstring(label) if label else None
                objc.objc_msgSend.argtypes = [
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
                ]
                objc.objc_msgSend(dock, sel_set_badge, ns_label)

            _can_set_badge = True
            print("ankibadge: using ctypes backend")
        except Exception as e:
            print(f"ankibadge: ctypes fallback failed: {e}")

from aqt import mw
from aqt import gui_hooks


def _get_due_count() -> int:
    """Return total due cards (new + learning + review) across all decks."""
    if mw.col is None:
        return 0
    tree = mw.col.sched.deck_due_tree()
    return tree.new_count + tree.learn_count + tree.review_count


def update_badge() -> None:
    """Update the Dock badge with the current due count."""
    if not _can_set_badge:
        return
    try:
        count = _get_due_count()
        label = str(count) if count > 0 else ""
        _set_dock_badge(label)
        print(f"ankibadge: badge set to {label!r}")
    except Exception as e:
        print(f"ankibadge: failed to update badge: {e}")


def _on_reviewer_did_answer(_reviewer, _card, _ease) -> None:
    update_badge()


def _on_collection_did_load(_col) -> None:
    update_badge()


# Register hooks
gui_hooks.main_window_did_init.append(update_badge)
gui_hooks.reviewer_did_answer_card.append(_on_reviewer_did_answer)
gui_hooks.sync_did_finish.append(update_badge)
gui_hooks.collection_did_load.append(_on_collection_did_load)

print(f"ankibadge: add-on loaded, badge support: {_can_set_badge}")
