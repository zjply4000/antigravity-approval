"""Jev permission evaluator for Antigravity (see docs/superpowers/specs)."""
import pathlib

if hasattr(pathlib, "_NormalAccessor") and hasattr(pathlib._NormalAccessor, "mkdir"):
    pathlib._NormalAccessor.mkdir = staticmethod(pathlib._NormalAccessor.mkdir)
