"""Settings window opened by the Config button: which counts the badge adds up."""

from typing import Callable

from aqt import mw
from aqt.qt import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .projection import is_counted

OPTIONS = (
    ("count_new", "New cards"),
    ("count_learning", "Learning cards"),
    ("count_review", "Due cards"),
)


def open_settings(addon: str, on_save: Callable[[], None]) -> None:
    config = mw.addonManager.getConfig(addon) or {}
    dialog = QDialog(mw.app.activeWindow() or mw)
    dialog.setWindowTitle("AnkiBadge")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Count in the badge:"))
    boxes = {}
    for key, label in OPTIONS:
        box = QCheckBox(label)
        box.setChecked(is_counted(config, key))
        layout.addWidget(box)
        boxes[key] = box
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec():
        config.update({key: box.isChecked() for key, box in boxes.items()})
        mw.addonManager.writeConfig(addon, config)
        on_save()
