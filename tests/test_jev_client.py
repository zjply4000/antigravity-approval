# tests/test_jev_client.py
import sys
import time
import types
from types import SimpleNamespace
import pytest
from jev_eval.config import Settings
from jev_eval.jev_client import evaluate_command, Verdict

def make_settings(**over):
    base = dict(api_key="sk-test", base_url="https://mock", confidence_threshold=0.96,
                eval_timeout_ms=1500, allow_network_commands=False, fail_mode="closed",
                log_file=None)
    base.update(over)
    return Settings(**base)

class FakeSDK:
    """Stands in for typesafe_sdk via sys.modules injection."""
    calls: list = []
    sleep: float = 0.0
    answer: dict = {"choice": "standard_dev", "confidence": 0.982}

    @classmethod
    def install(cls, monkeypatch):
        mod = types.ModuleType("typesafe_sdk")
        def make_client(model=None, retry_policy=None):
            client = SimpleNamespace()
            def system_one(state, questions):
                FakeSDK.calls.append(state)
                if FakeSDK.sleep:
                    time.sleep(FakeSDK.sleep)
                return SimpleNamespace(choices={"category": SimpleNamespace(**FakeSDK.answer)})
            client.system_one = system_one
            return client
        mod.TypeSafeClient = make_client
        class Choice:
            def __init__(self, instructions=None, criteria=None):
                self.instructions = instructions
                self.criteria = criteria
        mod.Choice = Choice
        mod.RetryPolicy = lambda **kw: SimpleNamespace(**kw)
        mod.TypeSafeAPIError = type("TypeSafeAPIError", (Exception,), {})
        monkeypatch.setitem(sys.modules, "typesafe_sdk", mod)

def test_happy_path(monkeypatch):
    FakeSDK.install(monkeypatch)
    FakeSDK.sleep = 0.0
    v, cause = evaluate_command("npm test", "C:/ws", ["C:/ws"], make_settings())
    assert v == Verdict("standard_dev", 0.982, v.latency_ms)
    assert v.latency_ms >= 0
    assert cause is None
    assert FakeSDK.calls[0]["command"] == "npm test"

def test_missing_key_short_circuits(monkeypatch):
    FakeSDK.calls = []
    v, cause = evaluate_command("npm test", "C:/ws", ["C:/ws"], make_settings(api_key=None))
    assert v is None
    assert "missing TYPESAFE_API_KEY" in cause
    assert FakeSDK.calls == []

def test_sdk_timeout_returns_none(monkeypatch):
    FakeSDK.install(monkeypatch)
    FakeSDK.sleep = 5.0
    start = time.perf_counter()
    v, cause = evaluate_command("npm test", "C:/ws", ["C:/ws"], make_settings(eval_timeout_ms=200))
    elapsed = time.perf_counter() - start
    assert v is None
    assert "deadline exceeded" in cause
    assert elapsed < 3.0  # hard external deadline, not the 5s sleep

def test_malformed_answer_returns_none(monkeypatch):
    FakeSDK.sleep = 0.0
    FakeSDK.install(monkeypatch)
    FakeSDK.answer = {"choice": "weird", "confidence": 0.99}
    v, cause = evaluate_command("npm test", "C:/ws", ["C:/ws"], make_settings())
    assert v is None
    assert "unknown Jev category" in cause
    FakeSDK.answer = {"choice": "standard_dev"}  # confidence missing -> AttributeError -> None
    v, cause = evaluate_command("npm test", "C:/ws", ["C:/ws"], make_settings())
    assert v is None
    assert "malformed Jev confidence" in cause

def test_import_failure_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "typesafe_sdk", None)  # import raises ImportError
    v, cause = evaluate_command("npm test", "C:/ws", ["C:/ws"], make_settings())
    assert v is None
    assert "not importable" in cause
