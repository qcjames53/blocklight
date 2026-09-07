# compile_file end-to-end testing

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


def test_multi_statement_body():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function hello:
    say one
    say two
    say three
""")
    assert out.errors == []
    assert out.files == {"hello_world/hello.mcfunction": "say one\nsay two\nsay three"}


def test_load_keyword_accepted():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
load function setup:
    say loading
""")
    assert out.errors == []
    assert out.files == {"hello_world/setup.mcfunction": "say loading"}


def test_tick_keyword_accepted():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
tick function loop:
    say ticking
""")
    assert out.errors == []
    assert out.files == {"hello_world/loop.mcfunction": "say ticking"}


def test_multiple_header_keywords():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
root load function setup:
    say loading
""")
    assert out.errors == []
    assert out.files == {"setup.mcfunction": "say loading"}


def test_line_continuation_in_body():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function hello:
    say the quick \\
        brown fox
""")
    assert out.errors == []
    assert out.files == {"hello_world/hello.mcfunction": "say the quick brown fox"}


def test_comments_and_blank_lines_ignored_in_body():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function hello:
    # a leading note
    say one

    # a note between statements
    say two
""")
    assert out.errors == []
    assert out.files == {"hello_world/hello.mcfunction": "say one\nsay two"}


def test_error_line_numbers_count_blank_and_comment_lines():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", """\
function hello:
    say one

    # filler that must still be counted
    say two
        over indented
""")
    assert len(out.errors) == 1
    assert out.errors[0].lineno == 6
    assert out.files == {}


def test_tab_indentation_allowed():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "hello_world", "function hello:\n\tsay one\n\tsay two\n")
    assert out.errors == []
    assert out.files == {"hello_world/hello.mcfunction": "say one\nsay two"}


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


def test_syntax_error_isolation():
    # A recoverable error in one function does not stop the others compiling.
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
    # A fatal error abandons the whole file, even functions that already compiled.
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
