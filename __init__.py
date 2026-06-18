"""
Anki Dock/Taskbar Badge Add-on
Shows total due cards (New + Learning + Review) as a badge on the app icon.
"""

import logging
from aqt import mw, gui_hooks
from aqt.qt import QGuiApplication

log = logging.getLogger(__name__)

_app = QGuiApplication.instance()
_can_set_badge = _app is not None and hasattr(_app, "setBadgeNumber")  # Qt 6.5+


def _get_due_count() -> int:
    if mw.col is None:
        return 0
    tree = mw.col.sched.deck_due_tree()
    return tree.new_count + tree.learn_count + tree.review_count


def update_badge() -> None:
    if not _can_set_badge:
        return
    try:
        _app.setBadgeNumber(_get_due_count())  # 0 clears it
    except Exception as e:
        log.warning("ankibadge: failed to update badge: %s", e)


def _on_change(changes, _handler) -> None:
    if changes.study_queues:        # top-level, no unwrapping needed
        update_badge()

gui_hooks.main_window_did_init.append(update_badge)
gui_hooks.collection_did_load.append(lambda _col: update_badge())  # first paint
gui_hooks.operation_did_execute.append(_on_change)                 # everything after
