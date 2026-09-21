# if/elif/else compilation: bare-if modifier-style compiles, chain dispatchers, condition parsing,
# and the standalone elif/else errors. See IF_ELIF_ELSE_PLAN.md for the design this exercises.

import blocklight
from tests.helpers import compile_source


def test_bare_if_compiles_like_a_modifier_block():
    out = compile_source("""\
function f
    if score @a v matches 1
        say a
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": (
            "execute if score @a v matches 1 run function pack:main/f_helper/chain_0_if"
        ),
        "data/pack/function/main/f_helper/chain_0_if.mcfunction": "say a",
    }


def test_if_else_chain_compiles_to_dispatcher_and_flat_branch_helpers():
    out = compile_source("""\
function f
    if score @a v matches 1
        say a
    else
        say b
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": "function pack:main/f_helper/chain_0",
        "data/pack/function/main/f_helper/chain_0.mcfunction": "\n".join(
            [
                "execute if score @a v matches 1 run return run function pack:main/f_helper/chain_0_if",
                "return run function pack:main/f_helper/chain_0_else",
            ]
        ),
        "data/pack/function/main/f_helper/chain_0_if.mcfunction": "say a",
        "data/pack/function/main/f_helper/chain_0_else.mcfunction": "say b",
    }


def test_if_elif_else_chain_with_multiple_elifs_numbers_them_by_position_in_the_chain():
    out = compile_source("""\
function f
    if score @a v matches 1
        say a
    elif score @a v matches 2
        say b
    elif score @a v matches 3
        say c
    else
        say d
""")
    assert out.errors == []
    dispatcher = out.file_contents["data/pack/function/main/f_helper/chain_0.mcfunction"]
    assert dispatcher == "\n".join(
        [
            "execute if score @a v matches 1 run return run function pack:main/f_helper/chain_0_if",
            "execute if score @a v matches 2 run return run function pack:main/f_helper/chain_0_elif_0",
            "execute if score @a v matches 3 run return run function pack:main/f_helper/chain_0_elif_1",
            "return run function pack:main/f_helper/chain_0_else",
        ]
    )
    assert out.file_contents["data/pack/function/main/f_helper/chain_0_elif_0.mcfunction"] == "say b"
    assert out.file_contents["data/pack/function/main/f_helper/chain_0_elif_1.mcfunction"] == "say c"


def test_if_elif_chain_without_else_has_no_trailing_unconditional_line():
    # 2+ branches still get a real dispatcher even without an `else` -- it just has no final
    # unconditional line, since falling through every condition is a valid (no-op) outcome.
    out = compile_source("""\
function f
    if score @a v matches 1
        say a
    elif score @a v matches 2
        say b
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f_helper/chain_0.mcfunction"] == "\n".join(
        [
            "execute if score @a v matches 1 run return run function pack:main/f_helper/chain_0_if",
            "execute if score @a v matches 2 run return run function pack:main/f_helper/chain_0_elif_0",
        ]
    )


def test_two_independent_chains_in_one_function_get_disjoint_chain_indices():
    out = compile_source("""\
function f
    if score @a v matches 1
        say a
    if score @a v matches 2
        say b
    else
        say c
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f.mcfunction"] == "\n".join(
        [
            "execute if score @a v matches 1 run function pack:main/f_helper/chain_0_if",
            "function pack:main/f_helper/chain_1",
        ]
    )
    assert "data/pack/function/main/f_helper/chain_0_if.mcfunction" in out.file_contents
    assert "data/pack/function/main/f_helper/chain_1_if.mcfunction" in out.file_contents
    assert "data/pack/function/main/f_helper/chain_1_else.mcfunction" in out.file_contents


def test_condition_parentheses_are_stripped_when_fully_wrapping():
    out = compile_source("""\
function f
    if (score @a v matches 1)
        say a
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f.mcfunction"] == (
        "execute if score @a v matches 1 run function pack:main/f_helper/chain_0_if"
    )


def test_condition_without_parentheses_passes_through_unchanged():
    out = compile_source("""\
function f
    if score @a v matches 1
        say a
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f.mcfunction"].startswith("execute if score @a v matches 1 ")


def test_condition_with_inner_parens_not_fully_wrapping_is_left_alone():
    # Only a single pair that wraps the *entire* condition is stripped -- one that merely happens
    # to start with '(' but closes before the end is untouched.
    out = compile_source("""\
function f
    if (score @a v matches 1) score @b v matches 2
        say a
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f.mcfunction"] == (
        "execute if (score @a v matches 1) score @b v matches 2 run function pack:main/f_helper/chain_0_if"
    )


def test_top_level_and_in_condition_is_rejected():
    out = compile_source("""\
function f
    if score @a v matches 1 and score @b v matches 2
        say a
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert "Boolean composition" in str(out.errors[0])
    assert out.file_contents == {}


def test_top_level_or_in_condition_is_rejected():
    out = compile_source("""\
function f
    if score @a v matches 1 or score @b v matches 2
        say a
""")
    assert len(out.errors) == 1
    assert "Boolean composition" in str(out.errors[0])


def test_leading_negated_group_in_condition_is_rejected():
    out = compile_source("""\
function f
    if !(score @a v matches 1)
        say a
""")
    assert len(out.errors) == 1
    assert "Boolean composition" in str(out.errors[0])


def test_standalone_elif_without_a_preceding_if_is_an_error():
    out = compile_source("""\
function f
    elif score @a v matches 1
        say a
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert "must immediately follow" in str(out.errors[0])
    assert out.file_contents == {}


def test_standalone_else_without_a_preceding_if_is_an_error():
    out = compile_source("""\
function f
    say hi
    else
        say a
""")
    assert len(out.errors) == 1
    assert "must immediately follow" in str(out.errors[0])


def test_elif_interrupted_by_an_unrelated_statement_is_an_error():
    out = compile_source("""\
function f
    if score @a v matches 1
        say a
    as @p
        say hi
    elif score @a v matches 2
        say b
""")
    assert len(out.errors) == 1
    assert "must immediately follow" in str(out.errors[0])


def test_while_block_between_if_and_elif_still_closes_the_chain():
    out = compile_source("""\
function f
    if score @a v matches 1
        say a
    while score @a v matches 2
        say b
    elif score @a v matches 3
        say c
""")
    assert len(out.errors) == 1
    assert "not yet implemented" in str(out.errors[0])


def test_if_chain_nested_inside_a_modifier_block():
    out = compile_source("""\
function f
    as @p
        if score @a v matches 1
            say a
        else
            say b
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f.mcfunction"] == (
        "execute as @p run function pack:main/f_helper/as_0"
    )
    assert out.file_contents["data/pack/function/main/f_helper/as_0.mcfunction"] == (
        "function pack:main/f_helper/as_0_helper/chain_0"
    )
    assert out.file_contents["data/pack/function/main/f_helper/as_0_helper/chain_0_if.mcfunction"] == "say a"
    assert out.file_contents["data/pack/function/main/f_helper/as_0_helper/chain_0_else.mcfunction"] == "say b"


def test_modifier_nested_inside_an_if_branch():
    out = compile_source("""\
function f
    if score @a v matches 1
        as @p
            say a
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f_helper/chain_0_if.mcfunction"] == (
        "execute as @p run function pack:main/f_helper/chain_0_if_helper/as_0"
    )
    assert out.file_contents["data/pack/function/main/f_helper/chain_0_if_helper/as_0.mcfunction"] == "say a"
