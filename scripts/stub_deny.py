#!/usr/bin/env python3
"""Bisection stub E: deny everything. If Antigravity hard-blocks every tool
call while this hook is active, hook stdout IS being read and only `allow`
is broken. If dialogs still appear (deny ignored too), this build does not
read hook decisions at all."""
import os
import sys

sys.stdout.write('{"decision": "deny", "reason": "stub E: deny test - everything blocked"}\n')
sys.stdout.flush()
os._exit(0)
