# Test file parsing tooling 

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
    assert blocklight.split_lines(source) == [
        ("line 2", 2),
        ("    line 3", 3),
        ("line 5 line 6 line 7", 5),
        ("\tline 8", 8),
    ]


def test_functions_iterator():
    source = """\
function a:
    foo
    bar
function b:
function c:
    foo
"""
    lines = blocklight.split_lines(source)
    assert list(blocklight.functions_iterator(lines)) == [
        (0, 3),
        (3, 4),
        (4, 6),
    ]


def test_functions_iterator_no_functions():
    assert list(blocklight.functions_iterator(blocklight.split_lines(""))) == []
    assert blocklight.compile_file("blank", "") == ([], [])