# Function header validation errors raised by compile_function

import blocklight


def test_top_level_line_is_not_a_function_header():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
say hello
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_header_declares_function_twice():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function function foo:
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_unknown_header_keyword():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
foo function hello:
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_duplicate_header_keyword():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
load load function hello:
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_header_missing_colon():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function hello
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_header_missing_function_name():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function :
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_function_name_has_illegal_characters():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function hello@all:
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}
