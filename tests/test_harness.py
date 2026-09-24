# One behavior check per block structure, exercising the compile harness end to end.

import blocklight
from tests.harness import compile_error, compile_pack


def test_modifier_blocks_record_context():
    run = compile_pack("""\
function f
    as @p
        at @s
            say hi
    say done
""").call("f")
    assert [(m.text, m.context) for m in run.messages] == [("hi", ("as @p", "at @s")), ("done", ())]


def test_if_elif_else_runs_exactly_one_branch():
    pack = compile_pack("""\
function f
    if score #x v matches 1
        say a
    elif score #x v matches 2
        say b
    else
        say c
    say end
""")
    for x, branch in [(1, "a"), (2, "b"), (3, "c")]:
        assert pack.call("f", objectives=["v"], scores={("#x", "v"): x}).said == [branch, "end"]


def test_nested_return_exits_the_whole_function():
    pack = compile_pack("""\
function f
    as @p
        if score #x v matches 1
            return 42
    say after
""")
    run = pack.call("f", objectives=["v"], scores={("#x", "v"): 1})
    assert (run.result, run.said) == ((True, 42), [])
    run = pack.call("f", objectives=["v"])
    assert (run.result, run.said) == (None, ["after"])


def test_while_loop_with_macros():
    run = compile_pack("""\
function f
    scoreboard players set #i v 0
    while score #i v matches ..$(max)
        say $(word)
        scoreboard players add #i v 1
""").call("f", macros={"max": 2, "word": "hi"}, objectives=["v"])
    assert run.said == ["hi", "hi", "hi"]


def test_python_block_emits_commands():
    run = compile_pack("""\
function f
    python
        for i in range(3):
            emit(f"say {i} {bl.FUNCTION_NAME}")
""").call("f")
    assert run.said == ["0 f", "1 f", "2 f"]


def test_root_and_load_functions():
    pack = compile_pack("""\
root load function setup
    scoreboard objectives add v dummy
""")
    assert pack.load_functions == {"test:setup"}
    assert pack.call("setup").result is None


def test_compile_error_reports_line():
    error = compile_error("""\
function f
    else
        say a
""")
    assert isinstance(error, blocklight.BLSyntaxError)
    assert error.lineno == 2
