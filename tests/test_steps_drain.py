"""Tests for the steps queue-drain + parser-reset helpers.

Validates the fix for the silent-steps-fetch bug: stale items left in
client.queues[CMD_GET_STEP_SOMEDAY] were being consumed by .get() before
the new request's response arrived, silently no-op'ing today's fetch.
"""
from __future__ import annotations

import asyncio

import pytest

from colmi_r02_client import steps as steps_mod
from colmi_r02_client.client import COMMAND_HANDLERS

from collector.protocol.parsers.steps import (
    _drain_steps_queue,
    _reset_steps_parser,
)


class _FakeClient:
    """Stand-in for collector.ring_client.Client — just the queues dict."""
    def __init__(self):
        self.queues = {steps_mod.CMD_GET_STEP_SOMEDAY: asyncio.Queue()}


# ----------------------------------------------------------------------------
# _drain_steps_queue
# ----------------------------------------------------------------------------


def test_drain_returns_zero_when_queue_empty():
    """Empty queue → drained count 0, no exception."""
    client = _FakeClient()
    assert _drain_steps_queue(client) == 0


def test_drain_removes_all_stale_items():
    """Multiple stale items → all removed, count returned."""
    client = _FakeClient()
    for item in (steps_mod.NoData(), steps_mod.NoData(), "garbage"):
        client.queues[steps_mod.CMD_GET_STEP_SOMEDAY].put_nowait(item)

    drained = _drain_steps_queue(client)

    assert drained == 3
    assert client.queues[steps_mod.CMD_GET_STEP_SOMEDAY].empty()


def test_drain_is_idempotent():
    """Calling drain twice is safe — second call is a no-op."""
    client = _FakeClient()
    client.queues[steps_mod.CMD_GET_STEP_SOMEDAY].put_nowait(steps_mod.NoData())

    assert _drain_steps_queue(client) == 1
    assert _drain_steps_queue(client) == 0


# ----------------------------------------------------------------------------
# _reset_steps_parser
# ----------------------------------------------------------------------------


def _parser_state():
    """Return (index, details_len, new_calorie_protocol) of the shared parser."""
    parser = COMMAND_HANDLERS[steps_mod.CMD_GET_STEP_SOMEDAY].__self__
    return parser.index, len(parser.details), parser.new_calorie_protocol


def test_reset_clears_parser_state():
    """After injecting stale state, reset() restores clean slate."""
    parser = COMMAND_HANDLERS[steps_mod.CMD_GET_STEP_SOMEDAY].__self__
    # Inject dirty state — simulate a truncated multi-packet sequence
    parser.index = 3
    parser.details = ["stale_slot_1", "stale_slot_2", "stale_slot_3"]
    parser.new_calorie_protocol = True

    _reset_steps_parser()

    assert parser.index == 0
    assert parser.details == []
    assert parser.new_calorie_protocol is False


def test_reset_is_safe_when_handler_missing(monkeypatch):
    """If COMMAND_HANDLERS doesn't have the steps key, reset is a no-op."""
    monkeypatch.setitem(
        COMMAND_HANDLERS, steps_mod.CMD_GET_STEP_SOMEDAY, lambda p: None
    )
    # Should not raise
    _reset_steps_parser()


# ----------------------------------------------------------------------------
# Regression: end-to-end drain+reset leaves clean state
# ----------------------------------------------------------------------------


def test_drain_then_reset_full_recovery():
    """Combined drain + reset restores pre-fetch clean state.

    This mirrors the fetch_steps prologue: drain queue, reset parser,
    then send fresh request. Verifies the helpers compose correctly.
    """
    client = _FakeClient()
    parser = COMMAND_HANDLERS[steps_mod.CMD_GET_STEP_SOMEDAY].__self__

    # Simulate prior incomplete fetch: stale queue items + dirty parser
    client.queues[steps_mod.CMD_GET_STEP_SOMEDAY].put_nowait(steps_mod.NoData())
    parser.index = 2
    parser.details = ["leftover"]

    drained = _drain_steps_queue(client)
    _reset_steps_parser()

    assert drained == 1
    assert client.queues[steps_mod.CMD_GET_STEP_SOMEDAY].empty()
    assert _parser_state() == (0, 0, False)
