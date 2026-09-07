# Test compilation of full files with basic functions (no blocks)

import blocklight


def test_basic_function():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function hello:
    say Hello, world!
""")
    assert out.errors == []
    assert out.files == {"hello_world/hello.mcfunction": "say Hello, world!"}


def test_basic_root_function():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
root function hello:
    say Hello, world!
""")
    assert out.errors == []
    assert out.files == {"hello.mcfunction": "say Hello, world!"}


def test_basic_function_filepath():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "foo/bar/baz", """\
function hello:
    say Hello, world!
""")
    assert out.errors == []
    assert out.files == {"foo/bar/baz/hello.mcfunction": "say Hello, world!"}


def test_function_funky_name():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function abcdefghijklmnopqrstuvwxyz_-0123456789:
    say Hello, world!
""")
    assert out.errors == []
    assert out.files == {"hello_world/abcdefghijklmnopqrstuvwxyz_-0123456789.mcfunction": "say Hello, world!"}


def test_unknown_header_keyword():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
foo function hello:
    say Hello, world!
""")
    assert out.files == {}
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1


def test_missing_header_colon():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function hello
    say Hello, world!
""")
    assert out.files == {}
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1


def test_missing_function_name():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function:
    say Hello, world!
""")
    assert out.files == {}
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1


def test_invalid_function_name():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function hello@all:
    say Hello, world!
""")
    assert out.files == {}
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1


def test_empty_file_produces_no_output():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", "")
    assert out.errors == []
    assert out.files == {}


def test_empty_function_produces_no_output():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function a:
function b:
    say Hello, world!
""")
    assert out.errors == []
    assert out.files == {"hello_world/b.mcfunction": "say Hello, world!"}


def test_indentation_enforcement():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function hello:
  say Hello, A!
    say Hello, B!
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    assert out.files == {}

    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function hello:
    say Hello, A!
  say Hello, B!
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    assert out.files == {}


def test_syntax_error_isolation():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function one:
    say Hello, world!
function two:
     say Hello, world!
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 4
    assert out.files == {"hello_world/one.mcfunction": "say Hello, world!"}


def test_fatal_error_prevents_all_output():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function one:
 say Hello, world!
function two:
    say Hello, world!
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLFatalError)
    assert out.errors[0].lineno == 2
    assert out.files == {}


def test_duplicate_output_path():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function hello:
    say first
function hello:
    say second
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    assert out.files == {"hello_world/hello.mcfunction": "say first"}


def test_errors_carry_filename_and_source_text():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function one:
    say Hello, world!
function two:
     say Hello, world!
""")
    assert len(out.errors) == 1
    err = out.errors[0]
    assert err.filename == "hello_world"
    assert err.lineno == 4
    assert err.text == "     say Hello, world!"


def test_fatal_error_carries_filename_and_source_text():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function one:
 say Hello, world!
""")
    assert len(out.errors) == 1
    err = out.errors[0]
    assert err.filename == "hello_world"
    assert err.lineno == 2
    assert err.text == " say Hello, world!"


def test_duplicate_output_path_error_points_at_function_definition():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function hello:
    say first
function hello:
    say second
""")
    err = out.errors[0]
    assert err.filename == "hello_world"
    assert err.lineno == 3
    assert err.text == "function hello:"
