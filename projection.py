"""Project the Dock badge number for the hours ahead, for when Anki is closed.

While Anki is closed nothing is studied, so the future due count follows from the
collection alone: learning cards come due at known times, and at each day rollover
buried cards return and the review/new daily limits reset.

Pure functions over an Anki collection (no GUI), so they can be tested headless.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

HOUR = 3600
DAY = 86400
HORIZON_HOURS = 7 * 24  # how far ahead to project
HOURLY_HOURS = 48  # learning cards come due within about a day, so only the
# first two days need hourly steps; after that only day rollovers change the number
MAX_POINTS = 50  # stay well under macOS's pending-notification limit


def _limit(col, deck_id: int, deck_key: str, conf_key: str) -> Optional[int]:
    """Per-day limit for a deck, or None if it has none (e.g. filtered decks)."""
    deck = col.decks.get(deck_id)
    if not deck or deck.get("dyn"):
        return None
    limit = deck.get(deck_key)
    if limit is None:
        limit = col.decks.config_dict_for_deck_id(deck_id)[conf_key]["perDay"]
    return limit


def _capped(
    col,
    node,
    review_own: dict[int, int],
    new_own: dict[int, int],
    new_ignores_review_limit: bool,
) -> tuple[int, int]:
    """(review, new) cards available under `node`, honouring the per-day limits at
    every level. Unless "new cards ignore review limit" is on, reviews use up the
    review limit before new cards can."""
    review = review_own.get(node.deck_id, 0)
    new = new_own.get(node.deck_id, 0)
    for child in node.children:
        child_review, child_new = _capped(
            col, child, review_own, new_own, new_ignores_review_limit
        )
        review += child_review
        new += child_new
    if node.deck_id:
        review_limit = _limit(col, node.deck_id, "reviewLimit", "rev")
        new_limit = _limit(col, node.deck_id, "newLimit", "new")
        if review_limit is not None:
            review = min(review, review_limit)
        if new_limit is not None:
            new = min(new, new_limit)
        if review_limit is not None and not new_ignores_review_limit:
            new = min(new, max(0, review_limit - review))
    return review, new


def _available_on_day(col, day: int) -> int:
    """New + review cards that will be available on collection day `day`,
    assuming no studying happens in between."""
    review: dict[int, int] = defaultdict(int)
    for did, n in col.db.all(
        # queue 2 = review; -2/-3 = buried, which come back at rollover
        "select did, count() from cards "
        "where type = 2 and queue in (2, -2, -3) and due <= ? group by did",
        day,
    ):
        review[did] = n
    new: dict[int, int] = defaultdict(int)
    for did, n in col.db.all(
        "select did, count() from cards "
        "where type = 0 and queue in (0, -2, -3) group by did"
    ):
        new[did] = n
    try:
        ignores = bool(col.get_config("newCardsIgnoreReviewLimit", False))
    except Exception:
        ignores = False
    root = col.decks.deck_tree()
    return sum(
        sum(_capped(col, child, review, new, ignores)) for child in root.children
    )


def _learning_due(col, by: int, day: int) -> int:
    """Learning cards due by epoch second `by` (intraday) or collection day `day`."""
    return col.db.scalar(
        "select count() from cards where "
        "(queue = 1 and due <= ?) or (queue = 3 and due <= ?)",
        by,
        day,
    )


def project_badge_counts(
    col, now: Optional[int] = None, hours: int = HORIZON_HOURS
) -> list[tuple[int, int]]:
    """Return [(epoch_second, badge_number)] for each moment the number changes.

    Evaluated hourly for the first HOURLY_HOURS plus at each day rollover within
    the horizon, capped at MAX_POINTS. The first value is compared against the
    number right now, so an unchanged number is never rescheduled.
    """
    now = int(time.time()) if now is None else now
    sched = col.sched
    today = sched.today
    cutoff = sched.day_cutoff

    horizon = now + hours * HOUR
    rollovers = []
    c = cutoff
    while c <= horizon:
        rollovers.append(c)
        c += DAY
    moments = sorted(
        {now + h * HOUR for h in range(1, min(hours, HOURLY_HOURS) + 1)}
        | set(rollovers)
    )

    tree = sched.deck_due_tree()
    remaining_today = tree.new_count + tree.review_count
    available_by_day: dict[int, int] = {}

    last = tree.new_count + tree.learn_count + tree.review_count
    points: list[tuple[int, int]] = []
    for t in moments:
        passed = sum(1 for r in rollovers if r <= t)
        day = today + passed
        if passed == 0:
            base = remaining_today
        else:
            if day not in available_by_day:
                available_by_day[day] = _available_on_day(col, day)
            base = available_by_day[day]
        value = base + _learning_due(col, t, day)
        if value != last:
            points.append((t, value))
            last = value
    return points[:MAX_POINTS]
