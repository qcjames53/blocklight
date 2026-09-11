# compile_file end-to-end testing

import blocklight


def test_basic_function():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
function hello:
    say Hello, world!
""",
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/hello.mcfunction": "say Hello, world!"}


def test_basic_root_function():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
root function hello:
    say Hello, world!
""",
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/hello_world/function/hello.mcfunction": "say Hello, world!"}


def test_basic_function_filepath():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/foo/blocklight/bar/baz.bl",
            source="""\
function hello:
    say Hello, world!
""",
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/foo/function/bar/baz/hello.mcfunction": "say Hello, world!"}


def test_function_funky_name():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
function abcdefghijklmnopqrstuvwxyz_-0123456789:
    say Hello, world!
""",
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {
        "data/hello_world/function/main/abcdefghijklmnopqrstuvwxyz_-0123456789.mcfunction": "say Hello, world!"
    }


def test_multi_statement_body():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
function hello:
    say one
    say two
    say three
""",
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/hello.mcfunction": "say one\nsay two\nsay three"}


def test_load_keyword_accepted():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
load function setup:
    say loading
""",
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/setup.mcfunction": "say loading"}


def test_tick_keyword_accepted():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
tick function loop:
    say ticking
""",
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/loop.mcfunction": "say ticking"}


def test_multiple_header_keywords():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
root load function setup:
    say loading
""",
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/hello_world/function/setup.mcfunction": "say loading"}


def test_line_continuation_in_body():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
function hello:
    say the quick \\
        brown fox
""",
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/hello.mcfunction": "say the quick brown fox"}


def test_comments_and_blank_lines_ignored_in_body():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
function hello:
    # a leading note
    say one

    # a note between statements
    say two
""",
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/hello.mcfunction": "say one\nsay two"}


def test_error_line_numbers_count_blank_and_comment_lines():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
function hello:
    say one

    # filler that must still be counted
    say two
        over indented
""",
        ),
        out,
    )
    assert len(out.errors) == 1
    assert out.errors[0].lineno == 6
    assert out.files == {}


def test_tab_indentation_allowed():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl", source="function hello:\n\tsay one\n\tsay two\n"
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/hello.mcfunction": "say one\nsay two"}


def test_empty_file_produces_no_output():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(blocklight.SourceFile(local_path="data/hello_world/blocklight/main.bl", source=""), out)
    assert out.errors == []
    assert out.files == {}


def test_empty_function_produces_no_output():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
function a:
function b:
    say Hello, world!
""",
        ),
        out,
    )
    assert out.errors == []
    assert out.files == {"data/hello_world/function/main/b.mcfunction": "say Hello, world!"}


def test_syntax_error_isolation():
    # A recoverable error in one function does not stop the others compiling.
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
function one:
    say Hello, world!
function two:
     say Hello, world!
""",
        ),
        out,
    )
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 4
    assert out.files == {"data/hello_world/function/main/one.mcfunction": "say Hello, world!"}


def test_fatal_error_prevents_all_output():
    # A fatal error abandons the whole file, even functions that already compiled.
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
function one:
 say Hello, world!
function two:
    say Hello, world!
""",
        ),
        out,
    )
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLFatalError)
    assert out.errors[0].lineno == 2
    assert out.files == {}


def test_errors_carry_filename_and_source_text():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
function one:
    say Hello, world!
function two:
     say Hello, world!
""",
        ),
        out,
    )
    assert len(out.errors) == 1
    err = out.errors[0]
    assert err.filename == "data/hello_world/blocklight/main.bl"
    assert err.lineno == 4
    assert err.text == "     say Hello, world!"


def test_fatal_error_carries_filename_and_source_text():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(
        blocklight.SourceFile(
            local_path="data/hello_world/blocklight/main.bl",
            source="""\
function one:
 say Hello, world!
""",
        ),
        out,
    )
    assert len(out.errors) == 1
    err = out.errors[0]
    assert err.filename == "data/hello_world/blocklight/main.bl"
    assert err.lineno == 2
    assert err.text == " say Hello, world!"
