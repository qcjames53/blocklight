# Structural and indentation errors raised by SourceFile.single_indent and _iter_spans

import blocklight
from tests.helpers import compile_source


def test_file_must_begin_with_function_definition():
    out = compile_source("""\
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLFatalError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_indent_schema_must_be_at_least_two_spaces():
    out = compile_source("""\
function hello:
 say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLFatalError)
    assert out.errors[0].lineno == 2
    assert out.files == {}


def test_indent_schema_may_not_mix_tabs_and_spaces():
    out = compile_source("function hello:\n\t say hi\n")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLFatalError)
    assert out.errors[0].lineno == 2
    assert out.files == {}


def test_body_line_under_indented():
    out = compile_source("""\
function hello:
    say a
  say b
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    assert out.files == {}


def test_body_line_over_indented():
    # Indent unit is settled as two spaces by 'function a'; 'function b' then opens
    # its body four spaces deep, which is over-indented for the first body line.
    out = compile_source("""\
function a:
  say a
function b:
    say b
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 4
    # Recoverable: the well-formed function still compiles.
    assert out.files == {"data/pack/function/main/a.mcfunction": "say a"}
