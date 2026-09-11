# Vanilla macro handling and CompiledBlockProperties reporting
# pyright: reportPrivateUsage=false

import blocklight
from tests.helpers import NO_HEADER, compile_source


def _props(source: str) -> blocklight._BlockOutput:
    # Compile the body of the first (only) function and return its accumulated output.
    sf = blocklight.SourceFile(local_path="data/pack/blocklight/main.bl", source=source)
    block_out = blocklight._BlockOutput()
    blocklight._compile_lines(blocklight._BlockInput(sf, "f", NO_HEADER), block_out, sf.source_lines[1:], 1)
    return block_out


def test_iter_macro_names_yields_names_in_order_with_duplicates():
    line = blocklight._Line("tp @s $(x) $(y) $(x)", 1)
    assert list(blocklight._iter_macro_names(line)) == ["x", "y", "x"]


def test_iter_macro_names_no_macros():
    assert list(blocklight._iter_macro_names(blocklight._Line("say plain text", 1))) == []


def test_iter_macro_names_allows_full_charset():
    assert list(
        blocklight._iter_macro_names(
            blocklight._Line("say $(ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz_0123456789)", 1)
        )
    ) == ["ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz_0123456789"]


def test_macro_line_gets_dollar_prefix():
    out = compile_source("""\
function hello:
    say hi $(name)
""")
    assert out.errors == []
    assert out.files == {"data/pack/function/main/hello.mcfunction": "$say hi $(name)"}


def test_macro_line_existing_dollar_prefix():
    out = compile_source("""\
function hello:
    $say hi $(name)
""")
    assert out.errors == []
    assert out.files == {"data/pack/function/main/hello.mcfunction": "$say hi $(name)"}


def test_plain_line_is_untouched():
    out = compile_source("""\
function hello:
    say hello
""")
    assert out.errors == []
    assert out.files == {"data/pack/function/main/hello.mcfunction": "say hello"}


def test_macros_recorded_on_properties():
    props = _props("""\
function hello:
    say $(greeting) $(name)
    playsound x block @s ~ ~ ~ 1 $(pitch)
""")
    assert props.macros == {"greeting", "name", "pitch"}


def test_no_macros_leaves_property_empty():
    props = _props("""\
function hello:
    say hello
""")
    assert props.macros == set()


def test_dollar_prefix_without_macro_is_an_error():
    out = compile_source("""\
function hello:
    say ok
    $say no macro here
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    assert out.files == {}


def test_unclosed_macro_is_an_error_at_its_source_line():
    out = compile_source("""\
function hello:
    say ok
    say $(unclosed
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    assert out.files == {}


def test_empty_macro_is_an_error():
    out = compile_source("""\
function hello:
    say $()
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.files == {}


def test_macro_name_rejects_invalid_characters():
    for bad in ("a b", "a-b", "a.b"):
        out = compile_source(f"function hello:\n    say $({bad})\n")
        assert len(out.errors) == 1
        assert isinstance(out.errors[0], blocklight.BLSyntaxError)
        assert out.errors[0].lineno == 2
        assert out.files == {}


def test_can_return_true_when_body_returns_a_value():
    props = _props("""\
function meaning_of_life:
    return 42
""")
    assert props.can_return is True


def test_can_return_true_for_bare_return_at_end_of_line():
    props = _props("""\
function f:
    execute if score #x tmp matches 1 run return
""")
    assert props.can_return is True


def test_can_return_false_without_a_return():
    props = _props("""\
function f:
    say hi
    scoreboard players set #x tmp 1
""")
    assert props.can_return is False
