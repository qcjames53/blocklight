# Vanilla macro handling and CompiledBlockProperties reporting

import blocklight


def test_iter_macro_names_yields_names_in_order_with_duplicates():
    line = blocklight._Line("tp @s $(x) $(y) $(x)", 1)
    assert list(blocklight._iter_macro_names(line)) == ["x", "y", "x"]


def test_iter_macro_names_no_macros():
    assert list(blocklight._iter_macro_names(blocklight._Line("say plain text", 1))) == []


def test_iter_macro_names_allows_full_charset():
    assert list(blocklight._iter_macro_names(blocklight._Line("say $(ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz_0123456789)", 1))) == ["ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz_0123456789"]


def test_macro_line_gets_dollar_prefix():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function hello:
    say hi $(name)
""")
    assert out.errors == []
    assert out.files == {"pack/hello.mcfunction": "$say hi $(name)"}


def test_macro_line_existing_dollar_prefix():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function hello:
    $say hi $(name)
""")
    assert out.errors == []
    assert out.files == {"pack/hello.mcfunction": "$say hi $(name)"}


def test_plain_line_is_untouched():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function hello:
    say hello
""")
    assert out.errors == []
    assert out.files == {"pack/hello.mcfunction": "say hello"}


def test_macros_recorded_on_properties():
    lines = blocklight._split_lines("""\
function hello:
    say $(greeting) $(name)
    playsound x block @s ~ ~ ~ 1 $(pitch)
""")
    ctx = blocklight._FileContext(local_path="pack", source_lines=lines)
    blocklight._detect_indent_schema(ctx)
    props = blocklight._compile_block(blocklight.CompiledOutput(), ctx, "pack/f.mcfunction", 1, len(ctx.source_lines), 1)
    assert props.macros == {"greeting", "name", "pitch"}


def test_no_macros_leaves_property_empty():
    lines = blocklight._split_lines("""\
function hello:
    say hello
""")
    ctx = blocklight._FileContext(local_path="pack", source_lines=lines)
    blocklight._detect_indent_schema(ctx)
    props = blocklight._compile_block(blocklight.CompiledOutput(), ctx, "pack/f.mcfunction", 1, len(ctx.source_lines), 1)
    assert props.macros == set()


def test_dollar_prefix_without_macro_is_an_error():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function hello:
    say ok
    $say no macro here
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    assert out.files == {}


def test_unclosed_macro_is_an_error_at_its_source_line():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function hello:
    say ok
    say $(unclosed
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.errors[0].lineno == 3
    assert out.files == {}


def test_empty_macro_is_an_error():
    out = blocklight.CompiledOutput()
    blocklight.compile_file(out, "pack", """\
function hello:
    say $()
""")
    assert len(out.errors) == 1
    assert isinstance(out.errors[0], blocklight.BLSyntaxError)
    assert out.files == {}


def test_macro_name_rejects_invalid_characters():
    for bad in ("a b", "a-b", "a.b"):
        out = blocklight.CompiledOutput()
        blocklight.compile_file(out, "pack", f"function hello:\n    say $({bad})\n")
        assert len(out.errors) == 1
        assert isinstance(out.errors[0], blocklight.BLSyntaxError)
        assert out.errors[0].lineno == 2
        assert out.files == {}


def test_can_return_true_when_body_returns_a_value():
    lines = blocklight._split_lines("""\
function meaning_of_life:
    return 42
""")
    ctx = blocklight._FileContext(local_path="pack", source_lines=lines)
    blocklight._detect_indent_schema(ctx)
    props = blocklight._compile_block(blocklight.CompiledOutput(), ctx, "pack/meaning_of_life.mcfunction", 1, len(ctx.source_lines), 1)
    assert props.can_return is True


def test_can_return_true_for_bare_return_at_end_of_line():
    lines = blocklight._split_lines("""\
function f:
    execute if score #x tmp matches 1 run return
""")
    ctx = blocklight._FileContext(local_path="pack", source_lines=lines)
    blocklight._detect_indent_schema(ctx)
    props = blocklight._compile_block(blocklight.CompiledOutput(), ctx, "pack/f.mcfunction", 1, len(ctx.source_lines), 1)
    assert props.can_return is True


def test_can_return_false_without_a_return():
    lines = blocklight._split_lines("""\
function f:
    say hi
    scoreboard players set #x tmp 1
""")
    ctx = blocklight._FileContext(local_path="pack", source_lines=lines)
    blocklight._detect_indent_schema(ctx)
    props = blocklight._compile_block(blocklight.CompiledOutput(), ctx, "pack/f.mcfunction", 1, len(ctx.source_lines), 1)
    assert props.can_return is False
