# tests/test_deterministic.py
from jev_eval.deterministic import split_chain, tokenize

def test_split_basic_operators():
    assert split_chain("git status && npm test") == ["git status", "npm test"]
    assert split_chain("a || b; c | d") == ["a", "b", "c", "d"]

def test_split_single_ampersand_and_newlines():
    assert split_chain("git status & rmdir /s /q build") == ["git status", "rmdir /s /q build"]
    assert split_chain("git status\r\nrm -rf /") == ["git status", "rm -rf /"]

def test_split_ignores_quoted_operators():
    assert split_chain('git commit -m "a && rm -rf /"') == ['git commit -m "a && rm -rf /"']
    assert split_chain('curl "http://x?a=1&b=2"') == ['curl "http://x?a=1&b=2"']

def test_split_masks_fd_redirects():
    assert split_chain("git diff 2>&1") == ["git diff 2>&1"]
    assert split_chain("a >| b") == ["a >| b"]  # >| masked so | does not split

def test_tokenize_strips_one_quote_layer():
    assert tokenize("git status") == ["git", "status"]
    assert tokenize('git commit -m "fix bug"') == ["git", "commit", "-m", "fix bug"]
    assert tokenize('"git" status') == ["git", "status"]
    assert tokenize("del C:\\tools\\build /s") == ["del", "C:\\tools\\build", "/s"]

def test_tokenize_unbalanced_quotes_returns_none():
    assert tokenize("echo 'unclosed") is None
