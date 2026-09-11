# Parsing helper validation
# pyright: reportPrivateUsage=false

import blocklight
from tests.helpers import compile_source


def test_split_lines():
    source = "\nline 2    \n    line 3        \n# line 4\nline 5 \\\n    line 6 \\\n        line 7\n\tline 8\n"
    assert blocklight.SourceFile._split_lines(source) == [
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
    ctx = blocklight.SourceFile(local_path="data/foo/blocklight/main.bl", source=source)
    assert list(blocklight._iter_spans(ctx.source_lines, ctx.single_indent, 0)) == [
        [("function a:", 1), ("    foo", 2), ("    bar", 3)],
        [("function b:", 4)],
        [("function c:", 5), ("    foo", 6)],
    ]


def test_span_iterator_no_functions():
    ctx = blocklight.SourceFile(local_path="data/foo/blocklight/main.bl", source="")
    assert list(blocklight._iter_spans(ctx.source_lines, ctx.single_indent, 0)) == []
    out = compile_source("", local_path="data/blank/blocklight/main.bl")
    assert out.files == {} and out.errors == []
