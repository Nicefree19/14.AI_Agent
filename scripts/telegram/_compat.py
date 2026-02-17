"""
Telegram library compatibility — resolves namespace collision.

The ``scripts/telegram/`` package shadows the third-party
``python-telegram-bot`` package.  This module provides
``get_bot_class()`` to safely import the real ``telegram.Bot``
class by temporarily manipulating ``sys.path``.

PTB v22+ uses httpx internally and resolves sub-modules (e.g.
``telegram._files.inputfile``) at runtime.  We must keep the real
``telegram`` package **permanently installed** in ``sys.modules``
under an alias so that Bot's internal imports succeed after the
initial import.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# Cache: loaded once, kept forever
_real_tg_module = None


def _import_real_telegram():
    """Import the real ``telegram`` module from *python-telegram-bot*.

    On first call, performs the namespace-collision workaround and
    permanently installs the real telegram package's sub-modules
    into ``sys.modules`` so that PTB's internal imports work.
    """
    global _real_tg_module
    if _real_tg_module is not None:
        return _real_tg_module

    _scripts_dir = str(Path(__file__).resolve().parent.parent)
    _project_root = str(Path(__file__).resolve().parent.parent.parent)
    _telegram_dir = str(Path(__file__).resolve().parent)

    # Temporarily remove conflict dirs from sys.path
    conflict_dirs = {_scripts_dir, _project_root, _telegram_dir, os.getcwd()}
    original_path = sys.path[:]
    sys.path = [
        p for p in sys.path if p not in conflict_dirs and not p.endswith("scripts")
    ]

    # Save our package refs
    our_telegram = sys.modules.pop("telegram", None)
    our_sub_modules = {
        k: v for k, v in sys.modules.items() if k.startswith("telegram.")
    }
    for k in our_sub_modules:
        sys.modules.pop(k, None)

    try:
        # Import the real package — this also populates sub-modules
        tg = importlib.import_module("telegram")

        # Snapshot all real telegram sub-modules that PTB loaded
        real_sub_modules = {
            k: v for k, v in sys.modules.items()
            if k.startswith("telegram.") and v is not None
        }

        _real_tg_module = tg
    finally:
        sys.path = original_path

    # Restore our package as the top-level "telegram" in sys.modules
    # so that `from scripts.telegram.xxx import ...` still works.
    if our_telegram is not None:
        sys.modules["telegram"] = our_telegram
    for k, v in our_sub_modules.items():
        sys.modules[k] = v

    # Permanently install PTB's internal sub-modules under their
    # real keys.  This is safe because our scripts never define
    # modules like ``telegram._bot`` or ``telegram._files``.
    for k, v in real_sub_modules.items():
        if k not in sys.modules:
            sys.modules[k] = v

    return _real_tg_module


def get_bot_class():
    """Import and return ``telegram.Bot`` from *python-telegram-bot*."""
    return _import_real_telegram().Bot


def get_input_file_class():
    """Import and return ``telegram.InputFile`` from *python-telegram-bot*."""
    return _import_real_telegram().InputFile
