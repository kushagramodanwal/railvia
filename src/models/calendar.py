"""Planning-calendar helpers.

Shared vocabulary, like the rest of `src.models` — the API, the generator and
the adapters all need to agree on which Monday a horizon starts, and none of
them should import another layer to find out.
"""

from __future__ import annotations

from datetime import date, timedelta

# Blocks are planned a week at a time from a Monday, so a horizon starts on
# one. Tests, benchmarks and the recorded demo pin this date, because a number
# you cannot reproduce is not worth quoting.
REFERENCE_MONDAY = date(2026, 3, 2)


def next_monday(today: date | None = None) -> date:
    """The Monday of the coming week — today, if today is a Monday.

    Skipping to the following week when someone opens the app on a Monday
    would hide the very week they are looking at.
    """
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)
