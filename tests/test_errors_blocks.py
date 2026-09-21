# Block body validation errors raised by compile_block

import blocklight
from tests.helpers import compile_source


def test_block_has_no_body():
    out = compile_source("""\
function hello
    if @s
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 2
    assert out.file_contents == {}


def test_while_block_not_yet_implemented():
    out = compile_source("""\
function hello
    while @s
        say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 2
    assert out.file_contents == {}


def test_plain_statement_may_not_open_an_indented_block():
    out = compile_source("""\
function hello
    say a
        say b
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    assert out.file_contents == {}
