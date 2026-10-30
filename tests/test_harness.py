# One behavior check per block structure, exercising the compile harness end to end.

import re

import pytest

import blocklight
from tests.harness import build, compile_error, compile_pack


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


def test_callee_return_does_not_leak_into_caller():
    pack = compile_pack("""\
function g
    return 5
function f
    function test:main/g
    if score #x v matches 1
        return 1
    say after
""")
    run = pack.call("f", objectives=["v"], scores={("#x", "v"): 0})
    assert (run.result, run.said) == (None, ["after"])


def test_nested_return_of_a_returning_function_exits_the_caller():
    pack = compile_pack("""\
function g
    as @s
        if score #x v matches 1
            return 1
    say g
function f
    as @s
        return run function test:main/g
    say after
""")
    run = pack.call("f", objectives=["v"], scores={("#x", "v"): 1})  # g returns 1
    assert (run.result, run.said) == ((True, 1), [])
    run = pack.call("f", objectives=["v"], scores={("#x", "v"): 0})  # g ends without returning, so f returns fail
    assert (run.result, run.said) == ((False, 0), ["g"])


@pytest.mark.parametrize(
    ("command", "result"),
    [
        ("return fail", (False, 0)),
        ("return run scoreboard players get #y v", (True, 7)),
        ("execute if score #y v matches 7 run return 3", (True, 3)),
        ("execute if score #y v matches 7 run return fail", (False, 0)),
    ],
    ids=["fail", "run", "inline", "inline fail"],
)
def test_each_nested_return_form_exits_the_whole_function(command: str, result: tuple[bool, int]):
    pack = compile_pack(f"function f\n    as @s\n        {command}\n    say after\n")
    run = pack.call("f", objectives=["v"], scores={("#y", "v"): 7})
    assert (run.result, run.said) == (result, [])
    assert run.scores["_bl"]["#_bl_returning"] == 0  # the return finished climbing


def test_return_inside_while_exits_the_whole_function():
    run = compile_pack("""\
function f
    scoreboard players set #i v 0
    while score #i v matches ..9
        scoreboard players add #i v 1
        if score #i v matches 3
            return run scoreboard players get #i v
    say after
""").call("f", objectives=["v"])
    assert (run.result, run.said) == ((True, 3), [])


def test_return_inside_elif_exits_the_whole_function():
    pack = compile_pack("""\
function f
    if score #x v matches 1
        say one
    elif score #x v matches 0
        return 4
    else
        say other
    say after
""")
    assert pack.call("f", objectives=["v"], scores={("#x", "v"): 0}).result == (True, 4)
    run = pack.call("f", objectives=["v"], scores={("#x", "v"): 1})
    assert (run.result, run.said) == (None, ["one", "after"])


def test_returns_at_the_function_level_stay_vanilla():
    pack = compile_pack("function f\n    execute if score #y v matches 1 run return 2\n    return 0\n")
    assert pack.functions["test:main/f"] == ["execute if score #y v matches 1 run return 2", "return 0"]


def test_while_loop_with_macros():
    run = compile_pack("""\
function f
    scoreboard players set #i v 0
    while score #i v matches ..$(max)
        say $(word)
        scoreboard players add #i v 1
""").call("f", macros={"max": 2, "word": "hi"}, objectives=["v"])
    assert run.said == ["hi", "hi", "hi"]


def test_dollar_prefixed_returns_exit_the_whole_function():
    pack = compile_pack("""\
function f
    as @s
        $execute if score #x v matches $(n) run return 1
        $return $(n)
    say after
""")
    run = pack.call("f", macros={"n": 1}, objectives=["v"], scores={("#x", "v"): 1})
    assert (run.result, run.said) == ((True, 1), [])
    run = pack.call("f", macros={"n": 7}, objectives=["v"], scores={("#x", "v"): 0})
    assert (run.result, run.said) == ((True, 7), [])


def test_dollar_prefixed_block_keyword_opens_a_block():
    run = compile_pack("""\
function f
    $if score #x v matches $(n)
        say hit
""").call("f", macros={"n": 1}, objectives=["v"], scores={("#x", "v"): 1})
    assert run.said == ["hit"]


def test_whole_command_macro_keeps_its_dollar():
    pack = compile_pack("function f\n    $(cmd)\n")
    assert pack.functions["test:main/f"] == ["$$(cmd)"]


def test_backslash_joins_the_next_line():
    pack = compile_pack("function f\n    say a \\\n        b\n")
    assert pack.functions["test:main/f"] == ["say a b"]


@pytest.mark.parametrize("gap", ["", "    # comment"], ids=["blank line", "comment line"])
def test_backslash_does_not_continue_past_a_gap(gap: str):
    pack = compile_pack(f"function f\n    say a \\\n{gap}\nfunction g\n    say b\n")
    assert pack.functions["test:main/f"] == ["say a"]
    assert pack.functions["test:main/g"] == ["say b"]


def test_bodiless_summon_is_the_vanilla_command():
    pack = compile_pack("function f\n    summon minecraft:zombie ~ ~ ~\n")
    assert pack.functions["test:main/f"] == ["summon minecraft:zombie ~ ~ ~"]


def test_python_output_is_cleaned_like_source():
    run = compile_pack("""\
function f
    python
        cmd("as @s   \\n    $say $(word)\\n    # dropped")
""").call("f", macros={"word": "hi"})
    assert run.said == ["hi"]


def test_python_block_emits_commands():
    run = compile_pack("""\
function f
    python
        for i in range(3):
            cmd(f"say {i} {FUNCTION_NAME}")
""").call("f")
    assert run.said == ["0 f", "1 f", "2 f"]


def test_python_block_defines_name_and_location_constants():
    run = compile_pack("""\
function f
    python
        cmd(f"say {SOURCE_FILEPATH} {FUNCTION_NAME} {FUNCTION_ID}")
        cmd(f"say {OUTPUT_FILEPATH} {HELPER_ID} {SIBLING_ID_PREFIX}")
    as @s
        python
            cmd(f"say {FUNCTION_ID} {HELPER_ID}")
""").call("f")
    assert run.said == [
        "data/test/blocklight/main.bl f test:main/f",
        "data/test/function/main/f.mcfunction test:main/f test:main/",
        "test:main/f test:main/f_helper/as_0",
    ]


def test_python_block_defines_pack_and_version_constants():
    run = compile_pack("""\
function f
    python
        cmd(f"say {PACK_NAME} {PACK_FORMAT}")
        cmd(f"say {BLOCKLIGHT_VERSION}")
""").call("f")
    assert run.said[0] == "pack 107"
    assert re.fullmatch(r"\d+\.\d+", run.said[1])


def test_python_block_constants_for_a_root_function():
    run = compile_pack("""\
root function f
    python
        cmd(f"say {FUNCTION_ID} {OUTPUT_FILEPATH}")
""").call("test:f")
    assert run.said == ["test:f data/test/function/f.mcfunction"]


def test_python_block_outside_a_function_has_no_function_constants():
    run = compile_pack("""\
python
    with blk("function f"):
        cmd(f"say {FUNCTION_NAME} {FUNCTION_ID} {HELPER_ID} {OUTPUT_FILEPATH} {SIBLING_ID_PREFIX}")
""").call("f")
    assert run.said == ["None None None None test:main/"]


def test_python_sibling_id_prefix_names_a_sibling_function():
    pack = compile_pack("""\
function f
    python
        cmd(f"function {SIBLING_ID_PREFIX}g")
function g
    say hi
""")
    assert pack.call("f").said == ["hi"]


def test_python_block_can_emit_blocks_beside_written_ones():
    run = compile_pack("""\
function f
    as @s
        say first
    python
        with blk("as @s"):
            cmd("say second")
""").call("f")
    assert run.said == ["first", "second"]


def test_python_block_can_continue_an_if_chain():
    pack = compile_pack("""\
function f
    if score #x v matches 1
        say one
    python
        for i in range(2, 4):
            with blk(f"elif score #x v matches {i}"):
                cmd(f"say {i}")
    else
        say other
""")
    for x, branch in [(1, "one"), (2, "2"), (3, "3"), (4, "other")]:
        assert pack.call("f", objectives=["v"], scores={("#x", "v"): x}).said == [branch]


def test_python_block_can_start_an_if_chain():
    pack = compile_pack("""\
function f
    python
        with blk("if score #x v matches 1"):
            cmd("say one")
    else
        say other
""")
    for x, branch in [(1, "one"), (2, "other")]:
        assert pack.call("f", objectives=["v"], scores={("#x", "v"): x}).said == [branch]


def test_empty_python_block_leaves_an_if_chain_open():
    pack = compile_pack("""\
function f
    if score #x v matches 1
        say one
    python
        pass
    else
        say other
""")
    for x, branch in [(1, "one"), (2, "other")]:
        assert pack.call("f", objectives=["v"], scores={("#x", "v"): x}).said == [branch]


def test_python_output_after_an_if_closes_the_chain():
    pack = compile_pack("""\
function f
    if score #x v matches 1
        say one
    python
        cmd("say after")
""")
    assert pack.call("f", objectives=["v"], scores={("#x", "v"): 1}).said == ["one", "after"]
    assert pack.call("f", objectives=["v"], scores={("#x", "v"): 2}).said == ["after"]


def test_python_block_can_emit_python_blocks():
    run = compile_pack("""\
function f
    python
        with blk("python"):
            cmd("cmd('say inner')")
        cmd("say outer")
""").call("f")
    assert run.said == ["inner", "outer"]


def test_top_level_python_block_emits_functions():
    pack = compile_pack("""\
python
    for i in range(2):
        with blk(f"function f{i}"):
            cmd(f"say {i}")
function g
    say g
""")
    assert pack.errors == []
    assert pack.call("f0").said == ["0"]
    assert pack.call("f1").said == ["1"]
    assert pack.call("g").said == ["g"]


def test_top_level_python_block_can_emit_load_functions():
    pack = compile_pack("""\
python
    with blk("load function setup"):
        cmd("say loaded")
""")
    assert pack.load_functions == {"_bl:load", "test:main/setup"}


def test_top_level_python_error_does_not_stop_later_functions():
    pack = build("""\
python
    raise ValueError("boom")
function g
    say g
""")
    assert [type(error) for error in pack.errors] == [blocklight.BLPythonError]
    assert pack.errors[0].lineno == 2
    assert pack.call("g").said == ["g"]


def test_top_level_python_block_must_emit_a_function_first():
    error = compile_error("""\
python
    cmd("    say hi")
""")
    assert isinstance(error, blocklight.BLSyntaxError)
    assert error.lineno == 1
    assert "must emit a function definition" in str(error)


def test_top_level_python_block_needs_a_body_and_no_arguments():
    assert "no body" in str(compile_error("python\n"))
    assert "does not permit arguments" in str(compile_error("python x\n    cmd('')\n"))


def test_python_emitted_elif_without_an_if_reports_the_python_block():
    error = compile_error("""\
function f
    say first
    python
        with blk("elif score #x v matches 1"):
            cmd("say one")
""")
    assert isinstance(error, blocklight.BLSyntaxError)
    assert error.lineno == 3
    assert "must immediately follow" in str(error)


def test_root_and_load_functions():
    pack = compile_pack("""\
root load function setup
    scoreboard objectives add v dummy
""")
    assert pack.load_functions == {"_bl:load", "test:setup"}
    assert pack.call("setup").result is None


def test_compile_error_reports_line():
    error = compile_error("""\
function f
    else
        say a
""")
    assert isinstance(error, blocklight.BLSyntaxError)
    assert error.lineno == 2


def test_python_blk_nests_with_the_files_own_indent():
    for unit in (" ", "  ", "    ", "\t"):
        src = "\n".join(
            [
                "function f",
                f"{unit}python",
                f"{unit * 2}with blk('as @s'):",
                f"{unit * 3}with blk('at @s'):",
                f"{unit * 4}cmd('say deep')",
                f"{unit * 3}cmd('say mid')",
                f"{unit * 2}cmd('say top')",
                "",
            ]
        )
        assert compile_pack(src).call("f").said == ["deep", "mid", "top"]


def test_python_blk_restores_depth_after_an_exception():
    error = compile_error("""\
function f
    python
        with blk("as @s"):
            raise ValueError("boom")
""")
    assert isinstance(error, blocklight.BLPythonError)


def test_python_errors_report_the_line_inside_the_block():
    raised = compile_error("""\
function f
    say first
    python
        x = 1
        # comment lines do not shift the report
        def boom():
            raise ValueError("boom")
        boom()
""")
    assert isinstance(raised, blocklight.BLPythonError)
    assert raised.lineno == 7
    invalid = compile_error("function f\n    python\n        x = 1\n        x = = 2\n")
    assert isinstance(invalid, blocklight.BLPythonError)
    assert invalid.lineno == 4


def test_backtick_expression_uses_state_from_an_earlier_python_block():
    run = compile_pack("""\
function f
    python
        word = "hi"
    say `word` there
""").call("f")
    assert run.said == ["hi there"]


def test_backtick_expression_sees_compile_constants():
    run = compile_pack("""\
function f
    say `FUNCTION_NAME` `SIBLING_ID_PREFIX`
""").call("f")
    assert run.said == ["f test:main/"]


def test_backtick_expression_leaves_braces_and_quotes_alone():
    run = compile_pack("""\
function f
    say {"a":"`1 + 1`"} \\"x\\"
""").call("f")
    assert run.said == ['{"a":"2"} \\"x\\"']


def test_double_backtick_is_a_literal_backtick():
    run = compile_pack("""\
function f
    say a``b `1`
""").call("f")
    assert run.said == ["a`b 1"]


def test_backticks_in_comments_and_python_bodies_are_not_expanded():
    run = compile_pack("""\
function f
    # `nope()`
    python
        cmd("say " + "``".join(["a", "b"]))  # the body is plain python; its emitted line is expanded like source
""").call("f")
    assert run.said == ["a`b"]


def test_backtick_expression_in_a_child_block_header():
    run = compile_pack("""\
function f
    python
        selector = "@p"
    as `selector`
        say hi
""").call("f")
    assert [(m.text, m.context) for m in run.messages] == [("hi", ("as @p",))]


def test_backtick_line_can_continue_an_if_chain():
    pack = compile_pack("""\
function f
    if score #x v matches 1
        say one
    `"elif"` score #x v matches 2
        say two
    else
        say other
""")
    for x, branch in [(1, "one"), (2, "two"), (3, "other")]:
        assert pack.call("f", objectives=["v"], scores={("#x", "v"): x}).said == [branch]


def test_unclosed_backtick_is_a_syntax_error():
    err = compile_error("function f\n    say `1\n")
    assert isinstance(err, blocklight.BLSyntaxError)
    assert "never closes" in str(err)


def test_backtick_expression_errors_point_at_the_line():
    err = compile_error("function f\n    say `missing`\n")
    assert isinstance(err, blocklight.BLPythonError)
    assert "NameError" in str(err)
    err = compile_error("function f\n    say `1 +`\n")
    assert isinstance(err, blocklight.BLPythonError)
    assert "invalid" in str(err)


def test_backtick_expression_cannot_produce_multiple_lines():
    err = compile_error('function f\n    say `"a\\nb"`\n')
    assert isinstance(err, blocklight.BLPythonError)
    assert "more than one line" in str(err)


def test_backtick_expression_is_rejected_without_python():
    err = compile_error("function f\n    say `1`\n", options=blocklight.CompilerOptions(no_python=True))
    assert isinstance(err, blocklight.BLSyntaxError)
    assert "disabled" in str(err)
