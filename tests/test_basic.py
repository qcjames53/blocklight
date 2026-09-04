def test_parent_function(compile_bl):
    result = compile_bl("hello_world.bl", """\
function:
    say Hello, world!
""")
    result.assert_only_files("hello_world.mcfunction")
    result.assert_file("hello_world.mcfunction", "say Hello, world!\n")


def test_named_function(compile_bl):
    result = compile_bl("hello_world.bl", """\
function hello:
    say Hello, world!
""")
    result.assert_only_files("hello_world/hello.mcfunction")
    result.assert_file("hello_world/hello.mcfunction", "say Hello, world!\n")
