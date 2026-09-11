# Output mcfunction collision errors raised by CompiledOutput

import blocklight
from tests.helpers import NO_HEADER, compile_source


def test_duplicate_function_name_in_one_file():
    out = compile_source("""\
function hello:
    say first
function hello:
    say second
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    # The first definition to compile wins; the collision is recoverable.
    assert out.files == {"data/pack/function/main/hello.mcfunction": "say first"}


def test_duplicate_output_error_points_at_the_function_definition():
    out = compile_source("""\
function hello:
    say first
function hello:
    say second
""")
    err = out.errors[0]
    assert err.filename == "data/pack/blocklight/main.bl"
    assert err.lineno == 3
    assert err.text == "function hello:"


def test_collision_between_two_files_sharing_a_root_output_path():
    out = blocklight.CompiledOutput()
    src_a = blocklight.SourceFile(
        local_path="data/pack/blocklight/a.bl", source="root function hello:\n    say from a\n"
    )
    src_b = blocklight.SourceFile(
        local_path="data/pack/blocklight/b.bl", source="root function hello:\n    say from b\n"
    )
    blocklight.compile_file(src_a, out, NO_HEADER)
    blocklight.compile_file(src_b, out, NO_HEADER)
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].filename == "data/pack/blocklight/b.bl"
    assert out.files == {"data/pack/function/hello.mcfunction": "say from a"}
