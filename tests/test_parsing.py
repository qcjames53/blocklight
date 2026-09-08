# Parsing helper validation

import blocklight


def test_split_lines():
    source = (
        "\n"
        "line 2    \n"
        "    line 3        \n"
        "# line 4\n"
        "line 5 \\\n"
        "    line 6 \\\n"
        "        line 7\n"
        "\tline 8\n"
    )
    assert blocklight._split_lines(source) == [
        ("line 2", 2),
        ("    line 3", 3),
        ("line 5 line 6 line 7", 5),
        ("\tline 8", 8),
    ]


def test_span_iterator_top_level():
    source = ("""\
function a:
    foo
    bar
function b:
function c:
    foo
""")
    ctx = blocklight._FileContext(local_path="foo", source_lines=blocklight._split_lines(source))
    assert list(blocklight._iter_spans(ctx, 0, len(ctx.source_lines), 0)) == [
        (0, 3),
        (3, 4),
        (4, 6),
    ]


def test_span_iterator_no_functions():
    ctx = blocklight._FileContext(local_path="foo", source_lines=blocklight._split_lines(""))
    assert list(blocklight._iter_spans(ctx, 0, len(ctx.source_lines), 0)) == []
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "blank", "")
    assert out.files == {} and out.errors == []