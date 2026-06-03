"""Logging configuration.

A single helper so every module logs the same way. The format is deliberately
greppable: LEVEL | component | message. Rules in .cursor/rules reference this
contract (e.g. poll failures log city + status + retry at WARNING).
"""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(levelname)s | %(name)s | %(message)s")
        )
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        _CONFIGURED = True
    return logging.getLogger(name)
