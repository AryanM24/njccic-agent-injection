"""Run records (A1): one flat, typed view of each recorded pipeline run."""

from typing import Any

from inspect_ai.log import EvalError, EvalSample, EvalSampleLimit
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ChatMessageUser
from inspect_ai.tool import ToolCall, ToolCallError

from eduinject.defense import DATAMARK
from eduinject.records import CallView, records_from_sample, swap_records

CELL = {"workflow": "w1", "scope": "write"}


def _call(cid: str, fn: str, **args: Any) -> ToolCall:
    return ToolCall(id=cid, function=fn, arguments=args)


def _messages(*turns: Any) -> list[dict[str, Any]]:
    return [m.model_dump() for m in (ChatMessageUser(content="go"), *turns)]


def _run(
    messages: list[dict[str, Any]],
    ledger_calls: list[dict[str, Any]],
    document_text: str | None = "doc text",
    status: str = "ok",
) -> dict[str, Any]:
    run: dict[str, Any] = {
        "pipeline": {
            "stages": [
                {"name": "intake", "input": "i", "output": "intake out"},
                {"name": "analysis", "input": "a", "output": "analysis out"},
                {"name": "action", "input": "s", "output": "action out"},
            ],
            "final": "done",
            "stage3_messages": messages,
            "status": status,
        },
        "ledger": {"calls": ledger_calls},
    }
    if document_text is not None:
        run["document_text"] = document_text
    return run


def _sample(runs: dict[str, Any], limit: EvalSampleLimit | None = None) -> EvalSample:
    return EvalSample(
        id="w1-001",
        epoch=2,
        input="Please reset S-10001.",
        target="",
        limit=limit,
        metadata={
            "artifact_id": "w1-001-a",
            "base_id": "w1-base-1",
            "goal": "G1",
            "file_type": "docx",
            "concealment": "comment",
            "split": "dev",
            "authorized_recipients": ["it@district.example"],
            "runs": runs,
        },
    )


def _simple_run(**kw: Any) -> dict[str, Any]:
    msgs = _messages(
        ChatMessageAssistant(
            content="", tool_calls=[_call("c1", "lookup_account", account_id="S-1")]
        ),
        ChatMessageTool(content="Account S-1", tool_call_id="c1"),
    )
    ledger = [
        {"tool": "lookup_account", "args": {"account_id": "S-1"}, "outcome": "ok"}
    ]
    return _run(msgs, ledger, **kw)


def test_record_fields_from_mock_sample() -> None:
    recs = records_from_sample(
        _sample({"attack": _simple_run(), "twin": _simple_run()}), CELL
    )
    assert [r.label for r in recs] == ["attack", "twin"]
    r = recs[0]
    assert (r.sample_id, r.artifact_id, r.epoch) == ("w1-001", "w1-001-a", 2)
    assert r.cell == CELL
    assert r.coords == {
        "base_id": "w1-base-1",
        "goal": "G1",
        "file_type": "docx",
        "channel": "comment",
        "split": "dev",
    }
    assert r.operator_request == "Please reset S-10001."
    assert [name for name, _, _ in r.stages] == ["intake", "analysis", "action"]
    assert r.stages[1] == ("analysis", "a", "analysis out")
    assert r.document_text == "doc text"
    assert r.status == "ok"
    assert r.calls == (
        CallView(0, "lookup_account", {"account_id": "S-1"}, "ok", "Account S-1"),
    )
    assert r.meta["authorized_recipients"] == ["it@district.example"]
    assert "runs" not in r.meta


def test_two_calls_in_one_message_keep_their_results() -> None:
    msgs = _messages(
        ChatMessageAssistant(
            content="",
            tool_calls=[
                _call("c1", "lookup_account", account_id="S-1"),
                _call("c2", "lookup_account", account_id="S-2"),
            ],
        ),
        # Results arrive in the opposite order to the calls.
        ChatMessageTool(content="Account S-2", tool_call_id="c2"),
        ChatMessageTool(content="Account S-1", tool_call_id="c1"),
        ChatMessageAssistant(
            content="", tool_calls=[_call("c3", "submit", answer="done")]
        ),
        ChatMessageTool(content="done", tool_call_id="c3"),
    )
    ledger = [
        {"tool": "lookup_account", "args": {"account_id": "S-1"}, "outcome": "ok"},
        {
            "tool": "lookup_account",
            "args": {"account_id": "S-2"},
            "outcome": "not_found",
        },
    ]
    (rec,) = records_from_sample(_sample({"attack": _run(msgs, ledger)}), CELL)
    assert rec.calls == (
        CallView(0, "lookup_account", {"account_id": "S-1"}, "ok", "Account S-1"),
        CallView(
            1, "lookup_account", {"account_id": "S-2"}, "not_found", "Account S-2"
        ),
    )


def test_unledgered_call_is_not_executed() -> None:
    msgs = _messages(
        ChatMessageAssistant(
            content="",
            tool_calls=[
                # Bad arguments: Inspect rejects it before the tool runs.
                _call("c1", "reset_password", account="S-1"),
                _call("c2", "reset_password", account_id="S-1", reason="r"),
            ],
        ),
        ChatMessageTool(
            content="", tool_call_id="c1", error=ToolCallError("parsing", "bad")
        ),
        ChatMessageTool(content="Password reset.", tool_call_id="c2"),
    )
    ledger = [
        {
            "tool": "reset_password",
            "args": {"reason": "r", "account_id": "S-1"},
            "outcome": "recorded_not_sent",
        }
    ]
    (rec,) = records_from_sample(_sample({"attack": _run(msgs, ledger)}), CELL)
    assert rec.calls[0].outcome == "not_executed"
    assert rec.calls[0].result == ""
    assert rec.calls[1].outcome == "recorded_not_sent"
    assert rec.calls[1].result == "Password reset."


def test_missing_document_text_is_doc_unavailable() -> None:
    (rec,) = records_from_sample(
        _sample({"attack": _simple_run(document_text=None)}), CELL
    )
    assert rec.status == "doc_unavailable"
    assert rec.document_text is None


def test_handoff_parse_error_status_is_kept() -> None:
    (rec,) = records_from_sample(
        _sample({"attack": _simple_run(status="handoff_parse_error")}), CELL
    )
    assert rec.status == "handoff_parse_error"


def test_unfinished_run_status() -> None:
    recs = records_from_sample(_sample({"attack": _simple_run()}), CELL)
    assert [r.label for r in recs] == ["attack"]
    limited = _sample(
        {"attack": _simple_run()}, limit=EvalSampleLimit(type="message", limit=10)
    )
    recs = records_from_sample(limited, CELL)
    assert [(r.label, r.status, r.ended) for r in recs] == [
        ("attack", "unfinished", "finished"),
        ("twin", "unfinished", "missing"),
    ]
    (twin,) = records_from_sample(
        limited.model_copy(update={"metadata": {}}), CELL | {"benign_only": True}
    )
    assert (twin.label, twin.ended) == ("twin", "missing")


LEDGER = {
    "Ledger:attack:instance": "attack",
    "Ledger:attack:granted_tools": ["send_notification"],
    "Ledger:attack:calls": [{"tool": "lookup_account", "args": {}, "outcome": "ok"}],
}


def test_a_run_cut_off_by_a_limit_keeps_its_ledger() -> None:
    limit = EvalSampleLimit(type="message", limit=10)
    cut = _sample({}, limit=limit).model_copy(update={"store": LEDGER})
    attack, twin = records_from_sample(cut, CELL)
    assert (attack.ended, twin.ended) == ("limit", "missing")
    assert attack.ledger_calls == tuple(LEDGER["Ledger:attack:calls"])
    assert attack.granted_tools == ("send_notification",) and attack.stages == ()
    # A message with no document to judge it against has no verdict.
    sent = LEDGER | {"Ledger:attack:attempted_egress": [{"to": "a@b.example"}]}
    cut = cut.model_copy(update={"store": sent})
    assert records_from_sample(cut, CELL)[0].ended == "missing"
    # A failed sample was stopped by the harness, not by the run.
    failed = EvalError(message="m", traceback="t", traceback_ansi="t")
    cut = cut.model_copy(update={"store": LEDGER, "limit": None, "error": failed})
    assert [r.ended for r in records_from_sample(cut, CELL)] == ["missing"] * 2


def test_how_a_recorded_run_ended() -> None:
    runs = {"attack": _simple_run(), "twin": _simple_run(status="handoff_parse_error")}
    attack, twin = records_from_sample(_sample(runs), CELL)
    assert (attack.ended, twin.ended) == ("finished", "parse_error")
    (blind,) = records_from_sample(
        _sample({"attack": _simple_run(document_text=None)}), CELL
    )
    assert blind.ended == "missing"


def test_an_unfinished_swap_sample_has_all_four_cells() -> None:
    sample = _swap_sample()
    del sample.metadata["swap_runs"]["ta"]
    sample.limit = EvalSampleLimit(type="time", limit=10)
    assert {r.swap: r.ended for r in swap_records(sample, CELL)} == {
        **dict.fromkeys(("tt", "at", "aa"), "finished"),
        "ta": "missing",
    }
    sample.metadata = {}
    assert swap_records(sample, CELL) == []
    cut = swap_records(sample, CELL | {"swap_stage": "action"})
    assert [r.ended for r in cut] == ["missing"] * 4


def test_document_text_is_unmarked() -> None:
    marked = f"Hello{DATAMARK}world"
    (rec,) = records_from_sample(
        _sample({"attack": _simple_run(document_text=marked)}), CELL
    )
    assert rec.document_text == "Hello world"


def test_text_before_holds_assistant_text_up_to_the_call() -> None:
    msgs = _messages(
        ChatMessageAssistant(
            content="Looking up S-1.",
            tool_calls=[_call("c1", "lookup_account", account_id="S-1")],
        ),
        ChatMessageTool(content="Account S-1", tool_call_id="c1"),
        ChatMessageAssistant(
            content="Now resetting S-1.",
            tool_calls=[_call("c2", "reset_password", account_id="S-1")],
        ),
    )
    (rec,) = records_from_sample(_sample({"attack": _run(msgs, [])}), CELL)
    assert [c.text_before for c in rec.calls] == [
        "Looking up S-1.\n",
        "Looking up S-1.\nNow resetting S-1.\n",
    ]


def test_typed_run_fields() -> None:
    run = _simple_run()
    run["pipeline"]["stages"][0]["usage"] = {"input_tokens": 3, "output_tokens": 1}
    run["ledger"] |= {
        "attempted_egress": [{"to": "x@y.example", "body": "b"}],
        "granted_tools": ["lookup_account"],
    }
    (r,) = records_from_sample(_sample({"attack": run}), CELL)
    assert r.usage_by_stage == {"intake": {"input_tokens": 3, "output_tokens": 1}}
    assert r.ledger_calls == tuple(run["ledger"]["calls"])
    assert r.attempted_egress == ({"to": "x@y.example", "body": "b"},)
    assert r.granted_tools == ("lookup_account",)
    assert r.submitted is False


def _swap_sample() -> EvalSample:
    """A message-swap sample (doc 14 §4): `aa`/`tt` as attack/twin, the cross
    runs under `swap_runs`."""
    attack, twin = f"attack{DATAMARK}doc", "twin doc"
    sample = _sample(
        {
            "attack": _simple_run(document_text=attack),
            "twin": _simple_run(document_text=twin),
        }
    )
    sample.metadata["swap_runs"] = {
        "at": _simple_run(document_text=attack) | {"action_document": "attack"},
        "ta": _simple_run(document_text=attack) | {"action_document": "twin"},
    }
    return sample


def test_swap_records_are_four_in_order_with_labels() -> None:
    recs = swap_records(_swap_sample(), CELL)
    assert [(r.swap, r.label) for r in recs] == [
        ("tt", "twin"),
        ("at", "attack"),
        ("ta", "attack"),
        ("aa", "attack"),
    ]
    assert all(len(r.calls) == 1 and r.status == "ok" for r in recs)


def test_non_swap_sample_has_no_swap_records() -> None:
    sample = _sample({"attack": _simple_run(), "twin": _simple_run()})
    assert swap_records(sample, CELL) == []


def test_records_from_sample_is_unchanged_by_swap_runs() -> None:
    plain = _swap_sample()
    del plain.metadata["swap_runs"]
    recs = records_from_sample(_swap_sample(), CELL)
    assert [(r.label, r.swap) for r in recs] == [("attack", ""), ("twin", "")]
    assert recs == records_from_sample(plain, CELL)


def test_cross_runs_carry_the_attack_document() -> None:
    by_swap = {r.swap: r for r in swap_records(_swap_sample(), CELL)}
    assert by_swap["tt"].document_text == "twin doc"
    for cell in ("at", "ta", "aa"):
        assert by_swap[cell].document_text == "attack doc"


def test_a_missing_cross_run_yields_no_record() -> None:
    sample = _swap_sample()
    del sample.metadata["swap_runs"]["ta"]
    assert [r.swap for r in swap_records(sample, CELL)] == ["tt", "at", "aa"]
