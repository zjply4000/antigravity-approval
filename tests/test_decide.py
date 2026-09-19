# tests/test_decide.py
from jev_eval.config import Settings
from jev_eval.decide import Decision, extract_args, finalize_tier2, decide
from jev_eval.jev_client import Verdict

def make_settings(**over):
    base = dict(api_key="sk", base_url="https://mock", confidence_threshold=0.96,
                eval_timeout_ms=1500, allow_network_commands=False, fail_mode="closed",
                log_file=None)
    base.update(over)
    return Settings(**base)

def test_extract_args_pascal_case():
    ex = extract_args("run_command", {"CommandLine": "git status", "Cwd": "C:/ws"})
    assert ex == {"command": "git status", "cwd": "C:/ws", "target": ""}

def test_extract_args_lowercase_fallback():
    ex = extract_args("run_command", {"command": "git status", "cwd": "C:/ws"})
    assert ex["command"] == "git status"

def test_extract_args_file_tools():
    ex = extract_args("write_to_file", {"TargetFile": "C:/ws/a.py"})
    assert ex["target"] == "C:/ws/a.py"
    ex2 = extract_args("replace_file_content", {"AbsolutePath": "C:/ws/b.py"})
    assert ex2["target"] == "C:/ws/b.py"

def test_extract_args_unknown_tool():
    assert extract_args("manage_task", {"anything": 1})["command"] == ""

def test_threshold_boundary():
    v_ok = Verdict("standard_dev", 0.96, 100)
    v_low = Verdict("standard_dev", 0.9599, 100)
    assert finalize_tier2(make_settings(), v_ok).decision == "allow"
    assert finalize_tier2(make_settings(), v_low).decision == "ask"

def test_destructive_and_network_escalate():
    assert finalize_tier2(make_settings(), Verdict("destructive", 0.99, 10)).decision == "ask"
    assert finalize_tier2(make_settings(), Verdict("network_outbound", 0.99, 10)).decision == "ask"

def test_network_allowed_with_flag():
    s = make_settings(allow_network_commands=True)
    assert finalize_tier2(s, Verdict("network_outbound", 0.97, 10)).decision == "allow"

def test_verdict_none_fail_modes():
    assert finalize_tier2(make_settings(), None).decision == "ask"
    assert finalize_tier2(make_settings(fail_mode="open"), None).decision == "allow"

def test_tier2_cause_reaches_reason():
    d = finalize_tier2(make_settings(), None, "missing TYPESAFE_API_KEY")
    assert d.decision == "ask" and "missing TYPESAFE_API_KEY" in d.reason

def test_decide_composes_tier1_and_tier2():
    s = make_settings()
    d1 = decide("run_command", {"CommandLine": "git status"}, ["C:/ws"], s, None)
    assert d1.decision == "allow" and d1.tier == "whitelist"
    d2 = decide("run_command", {"CommandLine": "npm test"}, ["C:/ws"], s, None)
    assert d2.decision == "ask" and d2.tier == "fallback"  # no verdict, closed mode
    d3 = decide("run_command", {"CommandLine": "npm test"}, ["C:/ws"], s,
                Verdict("standard_dev", 0.98, 90))
    assert d3.decision == "allow" and d3.tier == "jev" and d3.confidence == 0.98

def test_file_tool_asks_via_decide():
    d = decide("write_to_file", {"TargetFile": "C:/ws/a.py"}, ["C:/ws"], make_settings(), None)
    assert d.decision == "ask" and d.tier == "write_policy"

def test_unknown_tool_asks():
    d = decide("manage_task", {}, [], make_settings(), None)
    assert d.decision == "ask" and d.tier == "fallback"

def test_decision_defaults():
    d = Decision("ask", "why", "fallback")
    assert d.category is None and d.confidence is None and d.latency_ms is None
