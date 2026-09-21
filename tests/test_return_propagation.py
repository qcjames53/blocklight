# Return-through-nested-modifier-block propagation
# pyright: reportPrivateUsage=false

import blocklight
from tests.helpers import compile_source

RESET = "scoreboard players set #_bl_returning _bl 0"
SET_RETURNING = "scoreboard players set #_bl_returning _bl 1"
CHECK_OK = (
    "execute if score #_bl_returning _bl matches 1 if score #_bl_return_success _bl matches 1 "
    "run return run scoreboard players get #_bl_return_value _bl"
)
CHECK_FAIL = "execute if score #_bl_returning _bl matches 1 if score #_bl_return_success _bl matches 0 run return fail"
# Only the top-level (depth 1) function's own relay checks need to preserve success/fail -- nothing
# reads a helper's own return value, so a relay inside a helper just needs to halt.
RELAY_CHECK = "execute if score #_bl_returning _bl matches 1 run return 0"


def _call(prefix: str, target: str) -> str:
    return f"{prefix} run function {target}"


def _leaf(tail: str) -> list[str]:
    return [
        SET_RETURNING,
        "execute store result score #_bl_return_value _bl store success score #_bl_return_success _bl "
        f"run return {tail}",
    ]


def test_no_return_in_tree_is_unchanged_from_before_the_feature():
    # Pure backward-compatibility check: a block that can never return gets none of the machinery.
    out = compile_source("""\
function hello
    at @s
        say hi
    positioned ~ ~ ~
        say a
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/hello.mcfunction": "\n".join(
            [
                "execute at @s run function pack:main/hello_helper/at_0",
                "execute positioned ~ ~ ~ run function pack:main/hello_helper/positioned_0",
            ]
        ),
        "data/pack/function/main/hello_helper/at_0.mcfunction": "say hi",
        "data/pack/function/main/hello_helper/positioned_0.mcfunction": "say a",
    }


def test_bare_return_at_top_level_gets_entry_reset_and_flag():
    out = compile_source("""\
function meaning_of_life
    return 42
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/meaning_of_life.mcfunction": "\n".join([RESET, *_leaf("42")]),
    }


def test_single_level_modifier_block_return_propagates_to_top():
    out = compile_source("""\
function f
    as @p
        return 42
    say never
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": "\n".join(
            [RESET, _call("execute as @p", "pack:main/f_helper/as_0"), CHECK_OK, CHECK_FAIL, "say never"]
        ),
        "data/pack/function/main/f_helper/as_0.mcfunction": "\n".join(_leaf("42")),
    }


def test_two_level_nesting_matches_the_complete_return_example():
    # Mirrors tests/example_pack/.../functions.bl's `complete_return`: `as @p / at @s / return 42`
    # followed by a sibling command. Every level must propagate, and the sibling command is still
    # emitted (it's the runtime check that skips it, not the compiler). The outer (depth 1) relay
    # keeps the full success/fail check; the inner (depth 2) relay only needs to halt.
    out = compile_source("""\
function complete_return
    as @p
        at @s
            return 42
    say This will never run.
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/complete_return.mcfunction": "\n".join(
            [
                RESET,
                _call("execute as @p", "pack:main/complete_return_helper/as_0"),
                CHECK_OK,
                CHECK_FAIL,
                "say This will never run.",
            ]
        ),
        "data/pack/function/main/complete_return_helper/as_0.mcfunction": "\n".join(
            [
                _call("execute at @s", "pack:main/complete_return_helper/as_0_helper/at_0"),
                RELAY_CHECK,
            ]
        ),
        "data/pack/function/main/complete_return_helper/as_0_helper/at_0.mcfunction": "\n".join(_leaf("42")),
    }


def test_top_level_relay_keeps_full_check_but_nested_relay_only_halts():
    # Guards the depth boundary directly: the root function's own relay (depth 1) must keep
    # distinguishing success from fail, since it's the only level anything might actually observe.
    out = compile_source("""\
function f
    as @p
        at @s
            return 1
""")
    assert out.errors == []
    top = out.file_contents["data/pack/function/main/f.mcfunction"]
    as_0 = out.file_contents["data/pack/function/main/f_helper/as_0.mcfunction"]
    assert CHECK_OK in top
    assert CHECK_FAIL in top
    assert RELAY_CHECK in as_0
    assert CHECK_OK not in as_0
    assert CHECK_FAIL not in as_0


def test_can_return_bubbles_up_transitively_through_intermediate_helpers():
    # The intermediate `as_0` helper never itself writes the word "return" -- can_return must be
    # inherited from its own `at_0` child, not just detected lexically.
    out = compile_source("""\
function f
    as @p
        at @s
            return 1
""")
    assert out.errors == []
    as_0 = out.file_contents["data/pack/function/main/f_helper/as_0.mcfunction"]
    assert RELAY_CHECK in as_0
    top = out.file_contents["data/pack/function/main/f.mcfunction"]
    assert top.startswith(RESET)


def test_mixed_siblings_only_instruments_the_block_that_can_return():
    out = compile_source("""\
function mixed
    as @p
        return 1
    at @s
        say hi
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/mixed.mcfunction": "\n".join(
            [
                RESET,
                _call("execute as @p", "pack:main/mixed_helper/as_0"),
                CHECK_OK,
                CHECK_FAIL,
                "execute at @s run function pack:main/mixed_helper/at_0",
            ]
        ),
        "data/pack/function/main/mixed_helper/as_0.mcfunction": "\n".join(_leaf("1")),
        "data/pack/function/main/mixed_helper/at_0.mcfunction": "say hi",
    }


def test_return_fail_propagates_unchanged():
    out = compile_source("""\
function f
    as @p
        return fail
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f_helper/as_0.mcfunction"] == "\n".join(_leaf("fail"))
    assert CHECK_OK in out.file_contents["data/pack/function/main/f.mcfunction"]
    assert CHECK_FAIL in out.file_contents["data/pack/function/main/f.mcfunction"]


def test_return_run_command_is_passed_through_verbatim():
    out = compile_source("""\
function f
    as @p
        return run scoreboard players get #x obj
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f_helper/as_0.mcfunction"] == "\n".join(
        _leaf("run scoreboard players get #x obj")
    )


def test_inline_execute_return_is_extracted_into_its_own_helper():
    out = compile_source("""\
function f
    execute if entity @s run return 7
    say after
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": "\n".join(
            [
                RESET,
                "execute if entity @s run return run function pack:main/f_helper/return_0",
                "say after",
            ]
        ),
        "data/pack/function/main/f_helper/return_0.mcfunction": "\n".join(_leaf("7")),
    }


def test_inline_return_prefix_is_evaluated_exactly_once_not_duplicated():
    # `summon` has a side effect (it creates an entity); the whole point of extracting the return
    # into its own helper instead of duplicating the execute chain is that a modifier like this
    # only ever gets evaluated by the single `execute summon ... run return run function ...` call.
    out = compile_source("""\
function f
    execute summon minecraft:marker run return 1
""")
    assert out.errors == []
    top = out.file_contents["data/pack/function/main/f.mcfunction"]
    assert top.count("summon minecraft:marker") == 1
    assert "execute summon minecraft:marker run return run function" in top


def test_inline_return_inside_a_modifier_block_instruments_both_levels():
    out = compile_source("""\
function f
    as @p
        execute if entity @s run return 7
    say after
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": "\n".join(
            [RESET, _call("execute as @p", "pack:main/f_helper/as_0"), CHECK_OK, CHECK_FAIL, "say after"]
        ),
        "data/pack/function/main/f_helper/as_0.mcfunction": (
            "execute if entity @s run return run function pack:main/f_helper/as_0_helper/return_0"
        ),
        "data/pack/function/main/f_helper/as_0_helper/return_0.mcfunction": "\n".join(_leaf("7")),
    }


def test_multiple_inline_returns_get_uniquely_numbered_helpers():
    out = compile_source("""\
function multi
    execute if entity @s run return 1
    execute if entity @e run return 2
""")
    assert out.errors == []
    assert "data/pack/function/main/multi_helper/return_0.mcfunction" in out.file_contents
    assert "data/pack/function/main/multi_helper/return_1.mcfunction" in out.file_contents
    assert out.file_contents["data/pack/function/main/multi_helper/return_0.mcfunction"] == "\n".join(_leaf("1"))
    assert out.file_contents["data/pack/function/main/multi_helper/return_1.mcfunction"] == "\n".join(_leaf("2"))


def test_return_helper_numbering_does_not_collide_with_modifier_helper_numbering():
    out = compile_source("""\
function f
    as @p
        say hi
    execute if entity @s run return 1
""")
    assert out.errors == []
    assert "data/pack/function/main/f_helper/as_0.mcfunction" in out.file_contents
    assert "data/pack/function/main/f_helper/return_0.mcfunction" in out.file_contents


def test_macro_in_return_value_is_forwarded_through_the_extracted_helper():
    out = compile_source("""\
function f
    execute if entity @s run return $(v)
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f_helper/return_0.mcfunction"] == "\n".join(
        [
            SET_RETURNING,
            "$execute store result score #_bl_return_value _bl store success score #_bl_return_success _bl "
            "run return $(v)",
        ]
    )
    top = out.file_contents["data/pack/function/main/f.mcfunction"]
    assert top.splitlines()[1] == (
        '$execute if entity @s run return run function pack:main/f_helper/return_0 with {"v": "$(v)"}'
    )


def test_macro_in_execute_prefix_is_attributed_to_the_containing_function_not_the_helper():
    out = compile_source("""\
function f
    execute if score $(threshold) tmp matches 1.. run return 1
""")
    assert out.errors == []
    top = out.file_contents["data/pack/function/main/f.mcfunction"]
    assert top.splitlines()[1].startswith("$execute if score $(threshold) tmp matches 1..")
    # The extracted helper's own body has no macro use, so it should not be `$`-prefixed.
    helper = out.file_contents["data/pack/function/main/f_helper/return_0.mcfunction"]
    assert helper == "\n".join(_leaf("1"))


def test_word_return_in_an_unrelated_position_is_not_treated_as_a_return():
    # "return" preceded by something other than a leading position or "run " must not be rewritten
    # -- e.g. it might just be plain text in an ordinary command.
    out = compile_source("""\
function f
    say you must return home
""")
    assert out.errors == []
    assert out.file_contents == {"data/pack/function/main/f.mcfunction": "say you must return home"}


def test_word_return_inside_a_json_string_after_run_is_not_treated_as_a_return():
    out = compile_source("""\
function f
    execute run tellraw @a {"text":"return"}
""")
    assert out.errors == []
    assert out.file_contents == {"data/pack/function/main/f.mcfunction": 'execute run tellraw @a {"text":"return"}'}


def test_reset_line_is_inserted_after_the_header_comment_block():
    out = compile_source(
        """\
function f
    as @p
        return 1
""",
        options=blocklight.CompilerOptions(),
    )
    assert out.errors == []
    lines = out.raw_file_contents["data/pack/function/main/f.mcfunction"].splitlines()
    assert lines[0].startswith("# Compiled by Blocklight")
    assert lines[3] == RESET


def test_function_that_cannot_return_gets_no_reset_line():
    out = compile_source("""\
function f
    say hi
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f.mcfunction"] == "say hi"


def test_deeply_nested_three_levels_all_propagate():
    out = compile_source("""\
function f
    as @p
        at @s
            positioned ~ ~ ~
                return 5
""")
    assert out.errors == []
    top = out.file_contents["data/pack/function/main/f.mcfunction"]
    as_0 = out.file_contents["data/pack/function/main/f_helper/as_0.mcfunction"]
    at_0 = out.file_contents["data/pack/function/main/f_helper/as_0_helper/at_0.mcfunction"]
    positioned_0 = out.file_contents["data/pack/function/main/f_helper/as_0_helper/at_0_helper/positioned_0.mcfunction"]

    assert top.startswith(RESET)
    assert CHECK_OK in top
    assert CHECK_FAIL in top
    for level in (as_0, at_0):
        assert RELAY_CHECK in level
    assert positioned_0 == "\n".join(_leaf("5"))


# --- Interaction with if/elif/else chains ------------------------------------------------------


def test_bare_if_return_propagates_like_a_modifier_block():
    out = compile_source("""\
function f
    if score @a v matches 1
        return 1
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": "\n".join(
            [RESET, _call("execute if score @a v matches 1", "pack:main/f_helper/chain_0_if"), CHECK_OK, CHECK_FAIL]
        ),
        "data/pack/function/main/f_helper/chain_0_if.mcfunction": "\n".join(_leaf("1")),
    }


def test_if_else_chain_return_propagates_through_the_dispatcher_by_the_holder_scoreboards_alone():
    # The call into the dispatcher is a plain, unwrapped `function <dispatcher>` -- exactly like a
    # modifier's own child call -- because the branch that actually returns already set the
    # holder scoreboards itself; the dispatcher's own `return run` chaining only short-circuits
    # its sibling conditions and is never relied on to carry the value back out.
    out = compile_source("""\
function f
    if score @a v matches 1
        return 1
    else
        return 2
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": "\n".join(
            [RESET, "function pack:main/f_helper/chain_0", CHECK_OK, CHECK_FAIL]
        ),
        "data/pack/function/main/f_helper/chain_0.mcfunction": "\n".join(
            [
                "execute if score @a v matches 1 run return run function pack:main/f_helper/chain_0_if",
                "return run function pack:main/f_helper/chain_0_else",
            ]
        ),
        "data/pack/function/main/f_helper/chain_0_if.mcfunction": "\n".join(_leaf("1")),
        "data/pack/function/main/f_helper/chain_0_else.mcfunction": "\n".join(_leaf("2")),
    }


def test_if_chain_return_nested_inside_a_modifier_only_relays():
    out = compile_source("""\
function f
    as @p
        if score @a v matches 1
            return 1
        else
            return 2
""")
    assert out.errors == []
    top = out.file_contents["data/pack/function/main/f.mcfunction"]
    as_0 = out.file_contents["data/pack/function/main/f_helper/as_0.mcfunction"]
    assert top.startswith(RESET)
    assert CHECK_OK in top
    assert CHECK_FAIL in top
    assert RELAY_CHECK in as_0
    assert CHECK_OK not in as_0
    assert CHECK_FAIL not in as_0


def test_if_chain_with_no_return_gets_no_reset_line():
    out = compile_source("""\
function f
    if score @a v matches 1
        say a
    else
        say b
""")
    assert out.errors == []
    top = out.file_contents["data/pack/function/main/f.mcfunction"]
    assert not top.startswith(RESET)
    assert RESET not in top
