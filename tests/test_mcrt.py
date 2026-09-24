# Vanilla command semantics the mcrt interpreter must reproduce.

from collections.abc import Mapping

import pytest

from tests.mcrt import DEFAULT_COMMAND_LIMIT, Machine, McrtError, Message, Result, parse_snbt


# Machine over `functions` with an empty objective 'v'
def machine(
    functions: dict[str, list[str]],
    *,
    conditions: Mapping[str, bool] | None = None,
    command_limit: int = DEFAULT_COMMAND_LIMIT,
) -> Machine:
    m = Machine(functions, conditions=conditions, command_limit=command_limit)
    m.scores["v"] = {}
    return m


def test_function_without_return_is_void():
    assert machine({"t:f": ["say a"]}).call("t:f") is None


def test_return_value_fail_and_run():
    m = machine({"t:a": ["return 5"], "t:b": ["return fail"], "t:c": ["return run scoreboard players set #x v 3"]})
    assert m.call("t:a") == Result(True, 5)
    assert m.call("t:b") == Result(False, 0)
    assert m.call("t:c") == Result(True, 3)


def test_return_run_of_failing_command_fails():
    m = machine({"t:f": ["return run scoreboard players get #unset v", "say unreachable"]})
    assert m.call("t:f") == Result(False, 0)
    assert m.messages == []


def test_return_run_function_of_void_function_fails_and_exits():
    m = machine({"t:f": ["return run function t:g", "say unreachable"], "t:g": ["say g"]})
    assert m.call("t:f") == Result(False, 0)
    assert [msg.text for msg in m.messages] == ["g"]


def test_return_inside_execute_exits_the_function():
    m = machine({"t:f": ["execute as @p run return 1", "say unreachable"]})
    assert m.call("t:f") == Result(True, 1)
    assert m.messages == []


def test_return_inside_execute_store_reports_to_the_store():
    m = machine({"t:f": ["execute store result score #r v store success score #s v run return 9"]})
    assert m.call("t:f") == Result(True, 9)
    assert m.score("#r", "v") == 9
    assert m.score("#s", "v") == 1


def test_execute_store_of_void_function_stores_nothing():
    m = machine({"t:f": ["execute store result score #r v run function t:g"], "t:g": ["say g"]})
    m.call("t:f")
    assert m.score("#r", "v") is None


def test_execute_store_of_failed_command_stores_zero():
    m = machine({"t:f": ["execute store success score #r v run scoreboard players get #unset v"]})
    m.call("t:f")
    assert m.score("#r", "v") == 0


def test_if_function_passes_only_on_nonzero_success():
    m = machine(
        {
            "t:f": [
                f"execute if function t:{name} run say {name}" for name in ("one", "zero", "fail", "void", "macro")
            ],
            "t:one": ["return 1"],
            "t:zero": ["return 0"],
            "t:fail": ["return fail"],
            "t:void": ["say void"],
            "t:macro": ["$return $(x)"],
        }
    )
    m.call("t:f")
    assert [msg.text for msg in m.messages] == ["one", "void"]


def test_unset_score_fails_if_and_passes_unless():
    m = machine(
        {"t:f": ["execute if score #x v matches 0 run say if", "execute unless score #x v matches 0 run say un"]}
    )
    m.call("t:f")
    assert [msg.text for msg in m.messages] == ["un"]


def test_score_ranges_and_comparisons():
    m = machine({})
    m.scores["v"] = {"#a": 3, "#b": 5}
    for condition, expected in [
        ("#a v matches 3", True),
        ("#a v matches ..2", False),
        ("#a v matches 3..", True),
        ("#a v matches 1..4", True),
        ("#a v < #b v", True),
        ("#a v >= #b v", False),
        ("#a v = #unset v", False),
    ]:
        assert m.run(f"execute if score {condition}") == Result(expected, int(expected)), condition


def test_unknown_objective_fails_the_command():
    m = machine({})
    assert m.run("scoreboard players set #x missing 1") == Result(False, 0)
    assert m.run("execute store result score #x missing run say hi") == Result(False, 0)
    assert m.messages == []


def test_scoreboard_operations_use_floor_semantics_and_wrap():
    m = machine({})
    m.scores["v"] = {"#a": -7, "#b": 2, "#zero": 0, "#max": 2**31 - 1, "#one": 1}
    m.run("scoreboard players operation #a v /= #b v")
    assert m.score("#a", "v") == -4
    m.run("scoreboard players set #a v -7")
    m.run("scoreboard players operation #a v %= #b v")
    assert m.score("#a", "v") == 1
    m.run("scoreboard players operation #a v /= #zero v")
    assert m.score("#a", "v") == 1
    m.run("scoreboard players operation #max v += #one v")
    assert m.score("#max", "v") == -(2**31)
    m.run("scoreboard players operation #a v >< #b v")
    assert (m.score("#a", "v"), m.score("#b", "v")) == (2, 1)


def test_macro_substitution_and_missing_arguments_fail_the_call():
    m = machine({"t:f": ["say plain", "$say $(a) $(b)"]})
    assert m.run('function t:f {a: "x", b: 2}') is None
    assert m.run("function t:f") == Result(False, 0)
    assert m.run('function t:f with {a: "x"}') == Result(False, 0)
    assert [msg.text for msg in m.messages] == ["plain", "x 2"]


def test_modifiers_accumulate_context_across_function_calls():
    m = machine({"t:f": ["execute as @p positioned ~ ~1 ~ run function t:g"], "t:g": ["execute at @s run say hi"]})
    m.call("t:f")
    assert m.messages == [Message("say", "hi", ("as @p", "positioned ~ ~1 ~", "at @s"))]


def test_stubbed_conditions():
    m = machine({"t:f": ["execute if block ~ ~ ~ minecraft:water run say wet"]}, conditions={})
    with pytest.raises(McrtError, match="No stubbed outcome"):
        m.call("t:f")
    m = machine(
        {"t:f": ["execute if block ~ ~ ~ minecraft:water run say wet"]},
        conditions={"block ~ ~ ~ minecraft:water": True},
    )
    m.call("t:f")
    assert [msg.text for msg in m.messages] == ["wet"]


def test_tail_calls_do_not_grow_the_stack():
    m = machine(
        {
            "t:loop": [
                "scoreboard players add #i v 1",
                "execute unless score #i v matches 20000 run return run function t:loop",
            ]
        }
    )
    m.call("t:loop")
    assert m.score("#i", "v") == 20000


def test_command_limit():
    with pytest.raises(McrtError, match="command limit"):
        machine({"t:f": ["function t:f"]}, command_limit=100).call("t:f")


def test_unsupported_commands_raise():
    with pytest.raises(McrtError, match="Unsupported command"):
        machine({}).run("kill @e")


def test_parse_snbt():
    assert parse_snbt('{a: 1b, "b": "x", c: [1.5f, true], d: {}}') == {"a": 1, "b": "x", "c": [1.5, 1], "d": {}}
