# End-to-end test: runs the actual blocklight CLI against the example datapack, compiling it in
# place. Output is left on disk (see .gitignore) for inspection after a test run, but the test
# deletes any such leftovers from a prior run before compiling, so it stays idempotent even though
# manifest-driven caching would otherwise skip rewriting unchanged output (see test_manifest.py).
# Two functions use not-yet-implemented block keywords/features and are expected to fail and be
# reported on stderr.

import shutil
import subprocess
import sys
from pathlib import Path

import blocklight
from tests.helpers import strip_header

_BLOCKLIGHT_SCRIPT = Path(__file__).resolve().parents[1] / "blocklight.py"
_EXAMPLE_PACK = Path(__file__).resolve().parent / "example_pack"
_GENERATED_FUNCTION_DIR = _EXAMPLE_PACK / "data" / "bl_example" / "function"
_GENERATED_MANIFEST = _EXAMPLE_PACK / ".blocklight-manifest.json"

_EXPECTED_FILE_CONTENTS = {
    "data/bl_example/function/hello_root.mcfunction": "say Hello, root!",
    "data/bl_example/function/hello_universe.mcfunction": "say Hello, universe!",
    "data/bl_example/function/functions/hello.mcfunction": "say Hello, world!",
    "data/bl_example/function/functions/hello_load.mcfunction": "say Hello, load!",
    "data/bl_example/function/functions/hello_tick.mcfunction": "say Hello, tick!",
    "data/bl_example/function/fizzbuzz/fizzbuzz_runner.mcfunction": (
        'function bl_example:fizzbuzz/fizzbuzz with { "max": 20, "string_a": "Fizz", '
        '"string_b": "Buzz", "string_ab": "Fizzbuzz", "string_miss": "..." }'
    ),
    "data/bl_example/function/binary_search/ocean_floor_height_runner.mcfunction": (
        "scoreboard players set #low example_var -54\n"
        "scoreboard players set #high example_var 62\n"
        "scoreboard players set #mid example_var 4\n"
        "data modify storage bl_example targetY set value 4i\n"
        "execute store result score #result example_var run function bl_example:binary_search/ocean_floor_height "
        "with storage bl_example\n"
        'tellraw @s ["Ocean depth: ",{"score":{"name":"#result","objective":"example_var"}}]'
    ),
    "data/bl_example/function/macros/macros_demo_runner.mcfunction": (
        'function bl_example:macros/macros_demo_a with {"a": "hello"}'
    ),
    "data/bl_example/function/macros/macros_demo_a.mcfunction": (
        '$execute as @s run function bl_example:macros/macros_demo_a_helper/as_0 with {"a": "$(a)"}\n'
        '$function bl_example:macros/macros_demo_b with {"a": "$(a)"}'
    ),
    "data/bl_example/function/macros/macros_demo_a_helper/as_0.mcfunction": (
        '$execute at @s run function bl_example:macros/macros_demo_a_helper/as_0_helper/at_0 with {"a": "$(a)"}'
    ),
    "data/bl_example/function/macros/macros_demo_a_helper/as_0_helper/at_0.mcfunction": (
        "$execute positioned ~ ~ ~ run function "
        'bl_example:macros/macros_demo_a_helper/as_0_helper/at_0_helper/positioned_0 with {"a": "$(a)"}'
    ),
    "data/bl_example/function/macros/macros_demo_a_helper/as_0_helper/at_0_helper/positioned_0.mcfunction": (
        "$say $(a) from macros_demo_a"
    ),
    "data/bl_example/function/macros/macros_demo_b.mcfunction": "$say $(a) from macros_demo_b",
    "data/bl_example/function/python/hardcode_example.mcfunction": "\n".join(["say hi"] * 20),
    "data/bl_example/function/python/locators_example.mcfunction": (
        "say Relative filepath: 'data/bl_example/blocklight/python.bl'\n"
        "say Datapack name: 'example_pack'\n"
        "say Datapack format: '107'\n"
        "say Namespace: 'bl_example'\n"
        "say Source file: 'python.bl'\n"
        "say Top-level function name: 'locators_example'\n"
        "say Minecraft function name containing this script's output: 'bl_example:python/locators_example'\n"
        f"say Blocklight version: '{blocklight._BL_VERSION_STRING}'"  # pyright: ignore[reportPrivateUsage]
    ),
}

# Functions using not-yet-implemented block keywords/features (`while`; boolean composition in
# `if` conditions) must not compile.
_EXPECTED_MISSING_FILES = {
    "data/bl_example/function/fizzbuzz/fizzbuzz.mcfunction",
    "data/bl_example/function/binary_search/ocean_floor_height.mcfunction",
}

# (source basename, line) for the two expected recoverable errors, as they appear on stderr.
_EXPECTED_ERROR_FRAGMENTS = {
    "(fizzbuzz.bl, line 5)",
    "(binary_search.bl, line 8)",
}


def test_compiles_example_pack() -> None:
    shutil.rmtree(_GENERATED_FUNCTION_DIR, ignore_errors=True)
    _GENERATED_MANIFEST.unlink(missing_ok=True)

    result = subprocess.run(
        [sys.executable, str(_BLOCKLIGHT_SCRIPT)],
        cwd=_EXAMPLE_PACK,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

    for fragment in _EXPECTED_ERROR_FRAGMENTS:
        assert fragment in result.stderr

    for relative_path, contents in _EXPECTED_FILE_CONTENTS.items():
        assert strip_header((_EXAMPLE_PACK / relative_path).read_text()) == contents
    for relative_path in _EXPECTED_MISSING_FILES:
        assert not (_EXAMPLE_PACK / relative_path).exists()
