# Compiled by Blocklight 1.0.dev (https://github.com/qcjames53/blocklight)
# Changes saved to this file will not persist. Please modify the bl source file instead:
#     `data/bl_example/blocklight/fizzbuzz.bl:7`
scoreboard players operation #mod_a example_var = #i example_var
scoreboard players operation #mod_a example_var %= #3 example_var
scoreboard players operation #mod_b example_var = #i example_var
scoreboard players operation #mod_b example_var %= #5 example_var
$function bl_example:fizzbuzz/fizzbuzz_helper/while_0_body_helper/chain_0 {"string_a": "$(string_a)", "string_ab": "$(string_ab)", "string_b": "$(string_b)", "string_miss": "$(string_miss)"}
scoreboard players add #i example_var 1
$return run function bl_example:fizzbuzz/fizzbuzz_helper/while_0 {"max": "$(max)", "string_a": "$(string_a)", "string_ab": "$(string_ab)", "string_b": "$(string_b)", "string_miss": "$(string_miss)"}