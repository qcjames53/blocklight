# Output mcfunction collision errors raised by CompiledOutput

import blocklight


def test_duplicate_function_name_in_one_file():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="pack",
            source="""\
function hello:
    say first
function hello:
    say second
""",
        ),
        out,
    )
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    # The first definition to compile wins; the collision is recoverable.
    assert out.files == {"pack/hello.mcfunction": "say first"}


def test_duplicate_output_error_points_at_the_function_definition():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="pack",
            source="""\
function hello:
    say first
function hello:
    say second
""",
        ),
        out,
    )
    err = out.errors[0]
    assert err.filename == "pack"
    assert err.lineno == 3
    assert err.text == "function hello:"


def test_collision_between_two_files_sharing_a_root_output_path():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="pack_a",
            source="""\
root function hello:
    say from a
""",
        ),
        out,
    )
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="pack_b",
            source="""\
root function hello:
    say from b
""",
        ),
        out,
    )
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].filename == "pack_b"
    assert out.files == {"hello.mcfunction": "say from a"}
