# Macro propagation through recursively-compiled blocks (the `with {...}` forwarding chain)
# pyright: reportPrivateUsage=false

import blocklight
from tests.helpers import compile_source


def test_modifier_block_without_macros_gets_no_with_clause():
    out = compile_source("""\
function f:
    as @p:
        say hi
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": "execute as @p run function pack:main/f_helper/as_0",
        "data/pack/function/main/f_helper/as_0.mcfunction": "say hi",
    }


def test_single_macro_forwarded_through_one_level():
    out = compile_source("""\
function f:
    as @p:
        say $(x)
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": (
            '$execute as @p run function pack:main/f_helper/as_0 with {"x": "$(x)"}'
        ),
        "data/pack/function/main/f_helper/as_0.mcfunction": "$say $(x)",
    }


def test_multiple_distinct_macros_are_all_forwarded_sorted_alphabetically():
    out = compile_source("""\
function f:
    as @p:
        say $(zeta) $(alpha) $(mid)
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f.mcfunction"] == (
        '$execute as @p run function pack:main/f_helper/as_0 '
        'with {"alpha": "$(alpha)", "mid": "$(mid)", "zeta": "$(zeta)"}'
    )


def test_macro_referenced_multiple_times_is_forwarded_once():
    out = compile_source("""\
function f:
    as @p:
        say $(x) and $(x) again
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f.mcfunction"] == (
        '$execute as @p run function pack:main/f_helper/as_0 with {"x": "$(x)"}'
    )


def test_macro_forwards_through_three_levels_of_nesting():
    # Isolated unit-level equivalent of the example pack's macros_demo_a fixture.
    out = compile_source("""\
function f:
    as @p:
        at @s:
            positioned ~ ~ ~:
                say $(a) hi
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": (
            '$execute as @p run function pack:main/f_helper/as_0 with {"a": "$(a)"}'
        ),
        "data/pack/function/main/f_helper/as_0.mcfunction": (
            '$execute at @s run function pack:main/f_helper/as_0_helper/at_0 with {"a": "$(a)"}'
        ),
        "data/pack/function/main/f_helper/as_0_helper/at_0.mcfunction": (
            '$execute positioned ~ ~ ~ run function '
            'pack:main/f_helper/as_0_helper/at_0_helper/positioned_0 with {"a": "$(a)"}'
        ),
        "data/pack/function/main/f_helper/as_0_helper/at_0_helper/positioned_0.mcfunction": "$say $(a) hi",
    }


def test_sibling_block_without_macros_is_unaffected_by_a_macro_using_sibling():
    out = compile_source("""\
function f:
    as @p:
        say $(x)
    at @s:
        say hi
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": "\n".join(
            [
                '$execute as @p run function pack:main/f_helper/as_0 with {"x": "$(x)"}',
                "execute at @s run function pack:main/f_helper/at_0",
            ]
        ),
        "data/pack/function/main/f_helper/as_0.mcfunction": "$say $(x)",
        "data/pack/function/main/f_helper/at_0.mcfunction": "say hi",
    }


def test_macro_used_in_the_modifier_blocks_own_arguments_stays_local():
    # `$(pos)` is consumed directly by the `execute at ...` line in `f` itself, so `f` needs the
    # `$` prefix -- but the child block never references it, so no `with` clause is needed at all.
    out = compile_source("""\
function f:
    at $(pos):
        say hi
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": "$execute at $(pos) run function pack:main/f_helper/at_0",
        "data/pack/function/main/f_helper/at_0.mcfunction": "say hi",
    }


def test_macro_in_modifier_arguments_and_in_the_body_are_kept_separate():
    out = compile_source("""\
function f:
    at $(pos):
        say $(msg)
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f.mcfunction"] == (
        '$execute at $(pos) run function pack:main/f_helper/at_0 with {"msg": "$(msg)"}'
    )
    assert out.file_contents["data/pack/function/main/f_helper/at_0.mcfunction"] == "$say $(msg)"


def test_macro_already_dollar_prefixed_by_the_author_is_left_alone():
    out = compile_source("""\
function f:
    as @p:
        $say $(x)
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f_helper/as_0.mcfunction"] == "$say $(x)"


def test_python_emitted_line_inside_a_modifier_block_still_forwards_its_macro():
    out = compile_source("""\
function f:
    as @p:
        python:
            emit("say $(x)")
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f.mcfunction"] == (
        '$execute as @p run function pack:main/f_helper/as_0 with {"x": "$(x)"}'
    )
    assert out.file_contents["data/pack/function/main/f_helper/as_0.mcfunction"] == "$say $(x)"


def test_raw_function_call_macro_is_detected_without_a_dsl_block():
    # No `as`/`at`/etc. block involved -- just an ordinary pass-through line naming another
    # function and forwarding a macro into it by hand. `_iter_macro_names` scans the whole line
    # regardless of surrounding syntax, so this needs no special-casing anywhere in the compiler.
    out = compile_source("""\
function f:
    function pack:other with {"a": "$(a)"}
""")
    assert out.errors == []
    assert out.file_contents == {
        "data/pack/function/main/f.mcfunction": '$function pack:other with {"a": "$(a)"}',
    }


def test_malformed_macro_deep_inside_nested_blocks_is_still_reported_at_its_own_line():
    out = compile_source("""\
function f:
    as @p:
        at @s:
            say $(unclosed
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 4
    assert out.file_contents == {}


def test_invalid_macro_name_deep_inside_nested_blocks_is_still_reported():
    out = compile_source("""\
function f:
    as @p:
        at @s:
            say $(bad name)
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 4
    assert out.file_contents == {}


# --- Interaction with return propagation ---------------------------------------------------


def test_macro_in_extracted_return_value_is_forwarded_to_the_new_helper():
    out = compile_source("""\
function f:
    execute if entity @s run return $(v)
""")
    assert out.errors == []
    assert out.file_contents["data/pack/function/main/f.mcfunction"].splitlines()[1] == (
        '$execute if entity @s store result score #_bl_value _bl store success score #_bl_success _bl '
        'run function pack:main/f_helper/return_0 with {"v": "$(v)"}'
    )
    assert out.file_contents["data/pack/function/main/f_helper/return_0.mcfunction"] == "\n".join(
        ["scoreboard players set #_bl_returning _bl 1", "$return $(v)"]
    )


def test_macro_in_execute_prefix_of_an_embedded_return_stays_in_the_containing_function():
    out = compile_source("""\
function f:
    execute if score $(threshold) tmp matches 1.. run return 1
""")
    assert out.errors == []
    top = out.file_contents["data/pack/function/main/f.mcfunction"].splitlines()[1]
    assert top.startswith("$execute if score $(threshold) tmp matches 1..")
    assert '"threshold"' not in out.file_contents["data/pack/function/main/f_helper/return_0.mcfunction"]


def test_prefix_and_value_macros_on_the_same_embedded_return_are_kept_separate():
    out = compile_source("""\
function f:
    execute if score $(threshold) tmp matches 1.. run return $(value)
""")
    assert out.errors == []
    top = out.file_contents["data/pack/function/main/f.mcfunction"].splitlines()[1]
    # The prefix macro is used directly by this line and needs no forwarding into the helper...
    assert top.startswith("$execute if score $(threshold) tmp matches 1..")
    # ...only the macro actually used inside the extracted return needs a `with` clause.
    assert top.endswith('with {"value": "$(value)"}')
    assert out.file_contents["data/pack/function/main/f_helper/return_0.mcfunction"] == "\n".join(
        ["scoreboard players set #_bl_returning _bl 1", "$return $(value)"]
    )


def test_macro_forwards_through_a_modifier_block_that_also_returns():
    out = compile_source("""\
function f:
    as @p:
        say $(x)
        return 1
""")
    assert out.errors == []
    top = out.file_contents["data/pack/function/main/f.mcfunction"]
    assert top.splitlines()[1] == (
        '$execute as @p store result score #_bl_value _bl store success score #_bl_success _bl '
        'run function pack:main/f_helper/as_0 with {"x": "$(x)"}'
    )
    assert out.file_contents["data/pack/function/main/f_helper/as_0.mcfunction"] == "\n".join(
        ["$say $(x)", "scoreboard players set #_bl_returning _bl 1", "return 1"]
    )
