#!/usr/bin/env python3
"""Diagnostic stub: instantly allow every tool call, no evaluation, no stdin read.

TEMPORARY bisection tool for the Antigravity allow-honoring investigation.
Point hooks.json at this script (same interpreter) for one test round, then
restore the jev-evaluator hook. It never reads stdin (the payload fits the
pipe buffer) and never touches the network.
"""
import os
import sys

sys.stdout.write('{"decision": "allow", "reason": "stub: auto-allow for bisection"}\n')
sys.stdout.flush()
os._exit(0)
