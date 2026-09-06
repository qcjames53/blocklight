import blocklight


def test_basic_function():
    output, errors = blocklight.compile_file("hello_world", """\
function hello:
    say Hello, world!
""")
    assert errors == []
    assert output == [("hello_world/hello.mcfunction", "say Hello, world!\n")]


def test_basic_root_function():
    output, errors = blocklight.compile_file("hello_world", """\
root function hello:
    say Hello, world!
""")
    assert errors == []
    assert output == [("hello.mcfunction", "say Hello, world!\n")]


def test_basic_function_filepath():
    output, errors = blocklight.compile_file("foo/bar/baz", """\
function hello:
    say Hello, world!
""")
    assert errors == []
    assert output == [("foo/bar/baz/hello.mcfunction", "say Hello, world!\n")]


def test_function_funky_name():
    output, errors = blocklight.compile_file("hello_world", """\
function abcdefghijklmnopqrstuvwxyz_-0123456789:
    say Hello, world!
""")
    assert errors == []
    assert output == [("hello_world/abcdefghijklmnopqrstuvwxyz_-0123456789.mcfunction", "say Hello, world!\n")]


def test_unknown_header_keyword():
    output, errors = blocklight.compile_file("hello_world", """\
foo function hello:
    say Hello, world!
""")
    assert output == []
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLSyntaxError)
    assert errors[0].lineno == 1


def test_missing_header_colon():
    output, errors = blocklight.compile_file("hello_world", """\
function hello
    say Hello, world!
""")
    assert output == []
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLSyntaxError)
    assert errors[0].lineno == 1


def test_missing_function_name():
    output, errors = blocklight.compile_file("hello_world", """\
function:
    say Hello, world!
""")
    assert output == []
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLSyntaxError)
    assert errors[0].lineno == 1


def test_invalid_function_name():
    output, errors = blocklight.compile_file("hello_world", """\
function hello@all:
    say Hello, world!
""")
    assert output == []
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLSyntaxError)
    assert errors[0].lineno == 1


def test_empty_file_produces_no_output():
    output, errors = blocklight.compile_file("hello_world", "")
    assert errors == []
    assert output == []


def test_empty_function_produces_no_output():
    output, errors = blocklight.compile_file("hello_world", """\
function a:
function b:
    say Hello, world!
""")
    assert errors == []
    assert output == [("hello_world/b.mcfunction", "say Hello, world!\n")]


def test_indentation_enforcement():
    output, errors = blocklight.compile_file("hello_world", """\
function hello:
  say Hello, A!
    say Hello, B!
""")
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLSyntaxError)
    assert errors[0].lineno == 3
    assert output == []

    output, errors = blocklight.compile_file("hello_world", """\
function hello:
    say Hello, A!
  say Hello, B!
""")
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLSyntaxError)
    assert errors[0].lineno == 3
    assert output == []



def test_syntax_error_isolation():
    output, errors = blocklight.compile_file("hello_world", """\
function one:
    say Hello, world!
function two:
     say Hello, world!
""")
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLSyntaxError)
    assert errors[0].lineno == 4
    assert output == [("hello_world/one.mcfunction", "say Hello, world!\n")]


def test_fatal_error_prevents_all_output():
    output, errors = blocklight.compile_file("hello_world", """\
function one:
 say Hello, world!
function two:
    say Hello, world!
""")
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLFatalError)
    assert errors[0].lineno == 2
    assert output == []
