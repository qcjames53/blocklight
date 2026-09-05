def test_root_function(compile_bl):
    result = compile_bl("hello_world.bl", """\
root function hello:
    say Hello, world!
""")
    result.assert_file("hello.mcfunction", """\
say Hello, world!
""")


def test_named_function(compile_bl):
    result = compile_bl("hello_world.bl", """\
function hello:
    say Hello, world!
""")
    result.assert_file("hello_world/hello.mcfunction", """\
say Hello, world!
""")
