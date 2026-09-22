# Output mcfunction collision errors raised by CompiledOutput

import blocklight
from tests.helpers import compile_source, make_source_file, reset_for_test, strip_header, stub_disk_writes


def test_duplicate_function_name_in_one_file():
    out = compile_source("""\
function hello
    say first
function hello
    say second
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLFileError)
    assert out.errors[0].lineno == 3
    # The first definition to compile wins; the collision is recoverable.
    assert out.file_contents == {"data/pack/function/main/hello.mcfunction": "say first"}


def test_duplicate_output_error_points_at_the_function_definition():
    out = compile_source("""\
function hello
    say first
function hello
    say second
""")
    err = out.errors[0]
    assert err.filename == "data/pack/blocklight/main.bl"
    assert err.lineno == 3
    assert err.text == "function hello"


def test_collision_between_two_files_sharing_a_root_output_path():
    reset_for_test()
    compile_a = blocklight.Compile("data/pack/blocklight/a.bl", "pack")
    compile_b = blocklight.Compile("data/pack/blocklight/b.bl", "pack")
    src_a = make_source_file("data/pack/blocklight/a.bl", "root function hello\n    say from a\n")
    src_b = make_source_file("data/pack/blocklight/b.bl", "root function hello\n    say from b\n")
    with stub_disk_writes() as written:
        compile_a.compile(src_a)
        compile_b.compile(src_b)
        blocklight.orchestration.wait_for_writes()
    errors = blocklight.tui.get_errors()
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLFileError)
    assert errors[0].filename == "data/pack/blocklight/b.bl"
    assert {path: strip_header(content) for path, content in written.items()} == {
        "data/pack/function/hello.mcfunction": "say from a"
    }
