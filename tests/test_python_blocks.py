# `python:` block compilation

import blocklight


def _context(source):
    return blocklight.SourceFile(
        local_path="data/bl_example/blocklight/python.bl",
        source=source,
        pack_name="example_pack",
        pack_format=107,
        namespace="bl_example",
    )


def test_python_block_emit_repeats_a_command():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        _context("""\
function hardcode_example:
    python:
        for i in range(3):
            emit("say hi")
"""),
        out,
    )
    assert out.errors == []
    assert out.files == {
        "data/bl_example/function/python/hardcode_example.mcfunction": "say hi\nsay hi\nsay hi",
    }


def test_python_block_emit_uses_compile_time_logic():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        _context("""\
function grid:
    python:
        for i in range(3):
            x = f"~{i}" if i else "~"
            emit(f"setblock {x} ~ ~ stone")
"""),
        out,
    )
    assert out.errors == []
    assert out.files == {
        "data/bl_example/function/python/grid.mcfunction": (
            "setblock ~ ~ ~ stone\nsetblock ~1 ~ ~ stone\nsetblock ~2 ~ ~ stone"
        ),
    }


def test_python_block_interleaves_with_plain_commands():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        _context("""\
function mixed:
    say before
    python:
        emit("say from python")
    say after
"""),
        out,
    )
    assert out.errors == []
    assert out.files == {
        "data/bl_example/function/python/mixed.mcfunction": "say before\nsay from python\nsay after",
    }


def test_python_block_with_no_body_is_a_syntax_error():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        _context("""\
function empty:
    python:
    say after
"""),
        out,
    )
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 2
    assert out.files == {}


def test_python_block_emits_all_bl_constants():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        _context("""\
function locators_example:
    python:
        emit(f"say Relative filepath: '{bl.PATH}'")
        emit(f"say Datapack name: '{bl.PACK_NAME}'")
        emit(f"say Datapack format: '{bl.PACK_FORMAT}'")
        emit(f"say Namespace: '{bl.NAMESPACE}'")
        emit(f"say Source file: '{bl.FILE}'")
        emit(f"say Function name: '{bl.FUNCTION}'")
        emit(f"say Blocklight version: '{bl.BLOCKLIGHT_VERSION}'")
"""),
        out,
    )
    assert out.errors == []
    expected = "\n".join(
        [
            "say Relative filepath: 'data/bl_example/blocklight/python.bl'",
            "say Datapack name: 'example_pack'",
            "say Datapack format: '107'",
            "say Namespace: 'bl_example'",
            "say Source file: 'python.bl'",
            "say Function name: 'locators_example'",
            f"say Blocklight version: '{blocklight._BL_VERSION}'",
        ]
    )
    assert out.files == {"data/bl_example/function/python/locators_example.mcfunction": expected}


def test_python_block_emitted_commands_get_macro_handling():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        _context("""\
function macro_emit:
    python:
        emit("say hi $(name)")
"""),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/bl_example/function/python/macro_emit.mcfunction": "$say hi $(name)"}


def test_invalid_python_is_reported_as_bl_python_error():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        _context("""\
function broken:
    python:
        emit("say hi"
"""),
        out,
    )
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLPythonError)
    assert out.errors[0].lineno == 2  # points at the python: header
    assert out.files == {}


def test_python_runtime_error_is_reported_and_isolated():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        _context("""\
function py_error:
    python:
        raise ValueError("nope")
function fine:
    say ok
"""),
        out,
    )
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLPythonError)
    # the well-formed function still compiles
    assert out.files == {"data/bl_example/function/python/fine.mcfunction": "say ok"}


def test_python_block_that_emits_nothing_produces_an_empty_function():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        _context("""\
function silent:
    python:
        x = 1
"""),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/bl_example/function/python/silent.mcfunction": ""}


def test_emitted_output_is_recompiled_as_blocklight_source():
    # An emit()ed line that looks like a block keyword is routed back through the compiler, not
    # passed through verbatim. `as` blocks aren't implemented yet, so this surfaces that error
    # rather than writing a bogus "as @s:" command line.
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        _context("""\
function foo:
    python:
        emit("as @s:")
        emit("    say hi")
    say bye
"""),
        out,
    )
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert "'as' block is not yet implemented" in str(out.errors[0])
    assert out.files == {}
