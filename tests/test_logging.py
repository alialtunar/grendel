"""Tests for logging setup."""

from __future__ import annotations

import json
import logging

from grendel.logging_setup import configure_logging, get_logger


def test_json_lines_parse(capsys) -> None:
    configure_logging(level="INFO", fmt="json")
    log = get_logger("test")
    log.info("hello", extra={"target": "gpt"})
    err = capsys.readouterr().err
    line = err.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["target"] == "gpt"


def test_level_filter(capsys) -> None:
    configure_logging(level="WARNING", fmt="json")
    log = get_logger("test")
    log.debug("nope")
    log.warning("yep")
    err = capsys.readouterr().err
    assert "yep" in err
    assert "nope" not in err


def test_idempotent_single_handler() -> None:
    configure_logging(level="INFO", fmt="text")
    configure_logging(level="INFO", fmt="text")
    root = logging.getLogger("grendel")
    assert len(root.handlers) == 1


def test_get_logger_is_child() -> None:
    log = get_logger("cli")
    assert log.name == "grendel.cli"
