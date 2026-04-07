#!/usr/bin/env python3
"""Backward-compatible entry point for bulk challenge download.

Prefer the installed console script (after ``pip install -e .``)::

    ctf-pull --platform ctfd --output ./challenges

Or with environment from ``.env``::

    ctf-pull

See ``backend/pull_challenges_cli.py`` and ``backend/platforms/``.
"""

from __future__ import annotations

from backend.pull_challenges_cli import main

if __name__ == "__main__":
    main()
