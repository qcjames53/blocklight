# Compiled by Blocklight 1.0.dev (https://github.com/qcjames53/blocklight)
# Changes saved to this file will not persist. Please modify the bl source file instead:
#     `data/bl_example/blocklight/fizzbuzz.bl:13`
$execute if score #mod_a example_var matches 0 if score #mod_b example_var matches 0 run return run function bl_example:fizzbuzz/fizzbuzz_helper/while_0_body_helper/chain_0_if {"string_ab": "$(string_ab)"}
$execute if score #mod_a example_var matches 0 run return run function bl_example:fizzbuzz/fizzbuzz_helper/while_0_body_helper/chain_0_elif_0 {"string_a": "$(string_a)"}
$execute if score #mod_b example_var matches 0 run return run function bl_example:fizzbuzz/fizzbuzz_helper/while_0_body_helper/chain_0_elif_1 {"string_b": "$(string_b)"}
$return run function bl_example:fizzbuzz/fizzbuzz_helper/while_0_body_helper/chain_0_else {"string_miss": "$(string_miss)"}