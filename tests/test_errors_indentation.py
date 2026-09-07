# Structural and indentation errors raised by detect_indent_schema and span_iterator

import blocklight


def test_file_must_begin_with_function_definition():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
    say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLFatalError)
    assert out.errors[0].lineno == 1
    assert out.files == {}


def test_indent_schema_must_be_at_least_two_spaces():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function hello:
 say hi
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLFatalError)
    assert out.errors[0].lineno == 2
    assert out.files == {}


def test_indent_schema_may_not_mix_tabs_and_spaces():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", "function hello:\n\t say hi\n")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLFatalError)
    assert out.errors[0].lineno == 2
    assert out.files == {}


def test_body_line_under_indented():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
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
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function a:
  say a
function b:
    say b
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 4
    # Recoverable: the well-formed function still compiles.
    assert out.files == {"pack/a.mcfunction": "say a"}
