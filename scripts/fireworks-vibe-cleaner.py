#!/usr/bin/env python3
"""Portable launcher for a copied Agent Skill."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vibe_cleaner.cli import main  # noqa: E402

raise SystemExit(main())
