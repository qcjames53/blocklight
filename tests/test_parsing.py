# Parsing helper validation
# pyright: reportPrivateUsage=false

import blocklight
from tests.helpers import build_lines, compile_source, make_source_file


def test_iter_clean_lines():
    source = "\nline 2    \n    line 3        \n# line 4\nline 5 \\\n    line 6 \\\n        line 7\n\tline 8\n"
    assert build_lines(source) == [
        ("line 2", 2),
        ("    line 3", 3),
        ("line 5 line 6 line 7", 5),
        ("\tline 8", 8),
    ]


def test_span_iterator_top_level():
    source = """\
function a:
    foo
    bar
function b:
function c:
    foo
"""
    ctx = make_source_file("data/foo/blocklight/main.bl", source)
    assert list(blocklight.Compile._iter_spans(ctx.source_lines, blocklight.Compile._single_indent(ctx), 0)) == [
        [("function a:", 1), ("    foo", 2), ("    bar", 3)],
        [("function b:", 4)],
        [("function c:", 5), ("    foo", 6)],
    ]


def test_span_iterator_no_functions():
    ctx = make_source_file("data/foo/blocklight/main.bl", "")
    assert list(blocklight.Compile._iter_spans(ctx.source_lines, blocklight.Compile._single_indent(ctx), 0)) == []
    out = compile_source("", local_path="data/blank/blocklight/main.bl")
    assert out.file_contents == {} and out.errors == []
