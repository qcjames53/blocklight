# Function header validation errors raised by compile_function

import blocklight
from tests.helpers import compile_source


def test_top_level_line_is_not_a_function_header():
    out = compile_source("""\
say hello
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_header_declares_function_twice():
    out = compile_source("""\
function function foo:
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_unknown_header_keyword():
    out = compile_source("""\
foo function hello:
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_duplicate_header_keyword():
    out = compile_source("""\
load load function hello:
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_header_missing_colon():
    out = compile_source("""\
function hello
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_header_missing_function_name():
    out = compile_source("""\
function :
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_function_name_has_illegal_characters():
    out = compile_source("""\
function hello@all:
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 1
    assert out.files == {}
