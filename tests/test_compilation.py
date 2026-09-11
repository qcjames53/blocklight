# compile_file end-to-end testing
# pyright: reportPrivateUsage=false

import blocklight
from tests.helpers import NO_HEADER, compile_source


def _compile(
    source: str,
    *,
    local_path: str = "data/hello_world/blocklight/main.bl",
    options: blocklight.CompilerOptions = NO_HEADER,
):
    return compile_source(source, local_path=local_path, options=options)


def test_basic_function():
    out = _compile("""\
function hello:
    say Hello, world!
""")
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/hello.mcfunction": "say Hello, world!"}


def test_header_is_rendered_by_default():
    out = _compile(
        """\
function hello:
    say Hello, world!
""",
        options=blocklight.CompilerOptions(),
    )
    assert out.errors == []
    expected = "\n".join(
        [
            f"# Compiled by Blocklight {blocklight._BL_VERSION} (https://github.com/qcjames53/blocklight)",
            "# Changes saved to this file will not persist. Please modify the source file instead:",
            "#     `data/hello_world/blocklight/main.bl`",
            "say Hello, world!",
        ]
    )
    assert out.files == {"data/hello_world/function/main/hello.mcfunction": expected}


def test_basic_root_function():
    out = _compile("""\
root function hello:
    say Hello, world!
""")
    assert out.errors == []
    assert out.files == {"data/hello_world/function/hello.mcfunction": "say Hello, world!"}


def test_basic_function_filepath():
    out = _compile(
        """\
function hello:
    say Hello, world!
""",
        local_path="data/foo/blocklight/bar/baz.bl",
    )
    assert out.errors == []
    assert out.files == {"data/foo/function/bar/baz/hello.mcfunction": "say Hello, world!"}


def test_function_funky_name():
    out = _compile("""\
function abcdefghijklmnopqrstuvwxyz_-0123456789:
    say Hello, world!
""")
    assert out.errors == []
    assert out.files == {
        "data/hello_world/function/main/abcdefghijklmnopqrstuvwxyz_-0123456789.mcfunction": "say Hello, world!"
    }


def test_multi_statement_body():
    out = _compile("""\
function hello:
    say one
    say two
    say three
""")
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/hello.mcfunction": "say one\nsay two\nsay three"}


def test_load_keyword_accepted():
    out = _compile("""\
load function setup:
    say loading
""")
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/setup.mcfunction": "say loading"}


def test_tick_keyword_accepted():
    out = _compile("""\
tick function loop:
    say ticking
""")
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/loop.mcfunction": "say ticking"}


def test_multiple_header_keywords():
    out = _compile("""\
root load function setup:
    say loading
""")
    assert out.errors == []
    assert out.files == {"data/hello_world/function/setup.mcfunction": "say loading"}


def test_line_continuation_in_body():
    out = _compile("""\
function hello:
    say the quick \\
        brown fox
""")
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/hello.mcfunction": "say the quick brown fox"}


def test_comments_and_blank_lines_ignored_in_body():
    out = _compile("""\
function hello:
    # a leading note
    say one

    # a note between statements
    say two
""")
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/hello.mcfunction": "say one\nsay two"}


def test_error_line_numbers_count_blank_and_comment_lines():
    out = _compile("""\
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
    out = _compile("function hello:\n\tsay one\n\tsay two\n")
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/hello.mcfunction": "say one\nsay two"}


def test_empty_file_produces_no_output():
    out = _compile("")
    assert out.errors == []
    assert out.files == {}


def test_empty_function_produces_no_output():
    out = _compile("""\
function a:
function b:
    say Hello, world!
""")
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/b.mcfunction": "say Hello, world!"}


def test_syntax_error_isolation():
    # A recoverable error in one function does not stop the others compiling.
    out = _compile("""\
function one:
    say Hello, world!
function two:
     say Hello, world!
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 4
    assert out.files == {"data/hello_world/function/main/one.mcfunction": "say Hello, world!"}


def test_fatal_error_prevents_all_output():
    # A fatal error abandons the whole file, even functions that already compiled.
    out = _compile("""\
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
    out = _compile("""\
function one:
    say Hello, world!
function two:
     say Hello, world!
""")
    assert len(out.errors) == 1
    err = out.errors[0]
    assert err.filename == "data/hello_world/blocklight/main.bl"
    assert err.lineno == 4
    assert err.text == "     say Hello, world!"


def test_fatal_error_carries_filename_and_source_text():
    out = _compile("""\
function one:
 say Hello, world!
""")
    assert len(out.errors) == 1
    err = out.errors[0]
    assert err.filename == "data/hello_world/blocklight/main.bl"
    assert err.lineno == 2
    assert err.text == " say Hello, world!"
