"""
Regression guard: exception text must never be sent to API clients.

An AST scan of every backend module (tests/ and stale/ excluded) fails when, inside an
``except ... as <name>`` body, it finds

  (a) ``HTTPException(...)`` whose arguments reference the handler variable
      (``str(e)``, ``repr(e)``, f-strings, ``%`` / ``.format`` formatting, or the bare variable), or
  (b) a dict literal (or ``payload["error"] = ...`` assignment) with an
      "error" / "detail" / "message" style key whose value is built from the handler variable.
      This covers ``return {"error": str(e)}`` and JSON / WebSocket payload dicts.

The right fix is ``logger.exception("<what failed>")`` plus a fixed generic message.
If a message is *deliberately* client-safe (for example a validation error raised by our own code
with fixed or user-input-derived text), add it to ALLOWLIST below with a comment saying why.
"""
import ast
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXCLUDED_TOP_LEVEL = {"tests", "stale"}

# Dict keys whose values are shown to clients.
RESPONSE_KEYS = {"error", "errors", "detail", "message", "msg", "reason"}

# (path relative to backend/, snippet).  Matching is line-insensitive: the snippet only has to be a
# substring of the unparsed offending expression.  Every entry must still match a finding
# (test_allowlists_have_no_stale_entries), so remove entries when the code they excuse goes away.
ALLOWLIST = [
    # --- Deliberately client-safe: validation text raised by our own code ---------------------
    # BacktestInputError / ValueError messages come from our own validators (for example
    # "Unknown strategy 'x'", "initial_capital must be positive") and are returned as 400s so the
    # caller can fix the request.
    ("backtest/main.py", "HTTPException(status_code=400, detail=str(e))"),
    # Websocket path of the same validators: an HTTPException *we* raised with fixed text is
    # forwarded as the error payload (no raw exception text is involved).
    ("backtest/main.py", "{'error': http_err.detail}"),
    ("backtest/main.py", "{'status': 'error', 'error': http_err.detail}"),
    # run_backtest_service / run_multi_strategy_backtest turn ValueError / BacktestInputError from
    # _validate_run_settings and the strategy registry into an "error" dict; all other exceptions
    # are logged and replaced by INTERNAL_ERROR_MESSAGE.
    ("backtest/service.py", "{'error': str(e)}"),
    ("backtest/service.py", "'error': str(e), 'metrics': None"),
    # Strategy / period parameter validation raised by our own strategy registry and validators.
    ("technical/main.py", "HTTPException(status_code=400, detail=str(e))"),
    ("technical/main.py", "Invalid params for strategy"),
    # ReproduceError is our own typed error with a fixed, hand-written message.
    ("experiments/routes.py", "'message': exc.message"),
]

# Known leaks in modules that were outside the scope of the change that added this test (they are
# owned by other workstreams).  This list must only ever shrink: fix the code, then delete the
# entry.  New leaks must be fixed, not added here.
PENDING_FIXES = [
    ("backtest/core/groq_agent.py", "return f'Error calling Groq API: {str(e)}'"),
    ("backtest/core/groq_agent.py", "return f'Error calling Groq vision API: {str(e)}'"),
    ("chat/core/groq_agent.py", "return f'Error calling Groq API: {str(e)}'"),
    ("chat/core/groq_agent.py", "return f'Error calling Groq vision API: {str(e)}'"),
    ("chat/core/position_sizing_service.py", "{'error': str(e)}"),
    ("chat/core/research_service.py", "'error': str(e)"),
    ("chat/core/trade_levels_service.py", "'error': str(e)"),
    ("chat/stock_advisor.py", "return f'[Gemini error: {e}]'"),
    ("chat/stock_advisor.py", "return f'[Groq error: {e}]'"),
    ("portfolio/investor_profile.py", "HTTPException(status_code=422, detail=str(exc))"),
    ("portfolio/reports.py", "{'success': False, 'error': str(e)}"),
]


def _names_in(node: ast.AST) -> set:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _is_http_exception(call: ast.Call) -> bool:
    func = call.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    return name in {"HTTPException", "StarletteHTTPException", "WebSocketException"}


def _const_key(node):
    return node.value.lower() if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _is_text_built_from(value, var: str) -> bool:
    """True for f-strings, ``"..." % e``, ``"...".format(e)`` and ``str(e)`` / ``repr(e)`` returns."""
    if value is None or var not in _names_in(value):
        return False
    if isinstance(value, ast.JoinedStr):
        return True
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Mod):
        return True
    if isinstance(value, ast.Call):
        func = value.func
        if isinstance(func, ast.Name) and func.id in {"str", "repr"}:
            return True
        if isinstance(func, ast.Attribute) and func.attr == "format":
            return True
    return False


def find_leaks(source: str):
    """Return [(lineno, kind, snippet)] for every exception-text leak found in ``source``."""
    tree = ast.parse(source)
    leaks = []
    seen = set()

    def report(node, kind):
        key = (node.lineno, node.col_offset, kind)
        if key not in seen:
            seen.add(key)
            leaks.append((node.lineno, kind, ast.unparse(node)))

    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or not handler.name:
            continue
        var = handler.name
        for stmt in handler.body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Call) and _is_http_exception(node):
                    parts = list(node.args) + [kw.value for kw in node.keywords]
                    if any(var in _names_in(p) for p in parts):
                        report(node, "HTTPException")
                elif isinstance(node, ast.Dict):
                    for k, v in zip(node.keys, node.values):
                        if _const_key(k) in RESPONSE_KEYS and var in _names_in(v):
                            report(node, "dict")
                            break
                elif isinstance(node, ast.Return) and _is_text_built_from(node.value, var):
                    # return f"Error calling API: {e}"  (text that callers forward to clients)
                    report(node, "return-text")
                elif isinstance(node, ast.Assign):
                    # payload["message"] = f"... {e}"
                    for target in node.targets:
                        if (isinstance(target, ast.Subscript)
                                and _const_key(target.slice) in RESPONSE_KEYS
                                and var in _names_in(node.value)):
                            report(node, "assign")
    return leaks


def _matches(entries, rel_path: str, snippet: str) -> bool:
    return any(rel_path == path and allowed in snippet for path, allowed in entries)


def _allowed(rel_path: str, snippet: str) -> bool:
    return _matches(ALLOWLIST, rel_path, snippet)


def scan_backend_raw():
    """Every leak-shaped expression in backend/ as (rel_path, lineno, kind, snippet), no filtering."""
    found = []
    for path in sorted(BACKEND_DIR.rglob("*.py")):
        rel = path.relative_to(BACKEND_DIR)
        if rel.parts[0] in EXCLUDED_TOP_LEVEL or "__pycache__" in rel.parts:
            continue
        try:
            leaks = find_leaks(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:  # pragma: no cover - would be a real bug
            pytest.fail(f"cannot parse {rel.as_posix()}: {exc}")
        found.extend((rel.as_posix(), lineno, kind, snippet) for lineno, kind, snippet in leaks)
    return found


def scan_backend():
    return [
        f"{rel}:{lineno} [{kind}] {snippet}"
        for rel, lineno, kind, snippet in scan_backend_raw()
        if not _allowed(rel, snippet) and not _matches(PENDING_FIXES, rel, snippet)
    ]


def test_backend_has_no_new_exception_text_leaks():
    found = scan_backend()
    assert not found, (
        "Exception text is being sent to clients. Log it with logger.exception(...) and return a fixed "
        "generic message instead (or add a commented ALLOWLIST entry if it is deliberately "
        "client-safe):\n  " + "\n  ".join(found)
    )


def test_allowlists_have_no_stale_entries():
    raw = [(rel, snippet) for rel, _, _, snippet in scan_backend_raw()]
    for name, entries in (("ALLOWLIST", ALLOWLIST), ("PENDING_FIXES", PENDING_FIXES)):
        stale = [e for e in entries if not any(rel == e[0] and e[1] in snippet for rel, snippet in raw)]
        assert not stale, f"{name} entries no longer match any code, delete them: {stale}"


def test_mounted_routers_have_no_pending_leaks():
    """The routers this change is about must stay completely clean (no allowlist, no pending list)."""
    clean_roots = ("research/", "screener/", "dashboard/", "news/", "network/", "peers/", "markets/",
                   "sectors/", "core/", "services/", "chat/sentiment.py", "chat/super_agent.py",
                   "chat/research_legacy.py", "chat/pipelines.py")
    tolerated = [e for e in ALLOWLIST + PENDING_FIXES if e[0].startswith(clean_roots)]
    assert tolerated == []


# --------------------------------------------------------------------------- scanner self-checks

@pytest.mark.parametrize("source", [
    # HTTPException with str(e)
    "try:\n    f()\nexcept Exception as e:\n    raise HTTPException(status_code=500, detail=str(e))\n",
    # f-string / repr / % / format
    "try:\n    f()\nexcept Exception as e:\n    raise HTTPException(500, f'failed: {e}')\n",
    "try:\n    f()\nexcept Exception as exc:\n    raise HTTPException(500, detail=repr(exc))\n",
    "try:\n    f()\nexcept Exception as e:\n    raise HTTPException(500, detail='failed: %s' % e)\n",
    "try:\n    f()\nexcept Exception as e:\n    raise fastapi.HTTPException(500, detail='failed: {}'.format(e))\n",
    # returned dicts
    "try:\n    f()\nexcept Exception as e:\n    return {'error': str(e)}\n",
    "try:\n    f()\nexcept Exception as e:\n    return {'symbol': s, 'status': 'error', 'message': f'oops {e}'}\n",
    "try:\n    f()\nexcept Exception as e:\n    return JSONResponse(status_code=500, content={'detail': str(e)})\n",
    "async def ws():\n    try:\n        f()\n    except Exception as err:\n        await websocket.send_json({'type': 'error', 'message': str(err)})\n",
    # payload mutation
    "try:\n    f()\nexcept Exception as e:\n    payload['message'] = f'cached ({e})'\n",
])
def test_scanner_flags_synthetic_leaks(source):
    assert find_leaks(source), source


@pytest.mark.parametrize("source", [
    # fixed generic message + logging
    "try:\n    f()\nexcept Exception:\n    logger.exception('x')\n    raise HTTPException(500, 'Request failed')\n",
    "try:\n    f()\nexcept Exception as e:\n    logger.exception('x')\n    raise HTTPException(status_code=500, detail='Request failed')\n",
    "try:\n    f()\nexcept Exception as e:\n    logger.error('failed: %s', e)\n    return {'error': 'Request failed'}\n",
    # exception variable used outside a response key
    "try:\n    f()\nexcept Exception as e:\n    print(f'failed: {e}')\n    return {'error': 'Request failed', 'status': 'error'}\n",
    # same name outside an except body is not an exception variable
    "e = 'x'\nreturn_value = {'error': str(e)}\n",
])
def test_scanner_accepts_safe_patterns(source):
    assert find_leaks(source) == [], source


def test_allowlist_is_line_insensitive_and_path_specific():
    snippet = "HTTPException(status_code=400, detail=str(e))"
    assert _allowed("backtest/main.py", snippet)
    assert not _allowed("research/main.py", snippet)
