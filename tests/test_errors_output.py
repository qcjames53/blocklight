# Output mcfunction collision errors raised by CompiledOutput

import blocklight


def test_duplicate_function_name_in_one_file():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function hello:
    say first
function hello:
    say second
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    # The first definition to compile wins; the collision is recoverable.
    assert out.files == {"pack/hello.mcfunction": "say first"}


def test_duplicate_output_error_points_at_the_function_definition():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function hello:
    say first
function hello:
    say second
""")
    err = out.errors[0]
    assert err.filename == "pack"
    assert err.lineno == 3
    assert err.text == "function hello:"


def test_collision_between_two_files_sharing_a_root_output_path():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack_a", """\
root function hello:
    say from a
""")
    blocklight.compile_file(out, "pack_b", """\
root function hello:
    say from b
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].filename == "pack_b"
    assert out.files == {"hello.mcfunction": "say from a"}
