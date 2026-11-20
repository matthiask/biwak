"""Cursors of pages sorted by time, newest first (the feed, completed
to-dos): ``<microseconds since the epoch>,<id>`` of the last row shown.
The ID breaks ties between rows of the same time. The API has its own
cursors (``biwak/api_conventions.py``)."""

import datetime as dt


EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def encode(at, pk):
    delta = at - EPOCH
    micros = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    return f"{micros},{pk}"


def decode(value):
    """The time and ID of a cursor; ``ValueError`` if it isn't one"""
    micros, pk = value.split(",")
    try:
        return EPOCH + dt.timedelta(microseconds=int(micros)), int(pk)
    except OverflowError as error:
        raise ValueError(value) from error
