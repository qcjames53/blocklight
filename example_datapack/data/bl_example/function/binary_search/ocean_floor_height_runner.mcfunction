# Compiled by Blocklight 1.0.dev (https://github.com/qcjames53/blocklight)
# Changes saved to this file will not persist. Please modify the bl source file instead:
#     `data/bl_example/blocklight/binary_search.bl:24`
scoreboard players set #low example_var -54
scoreboard players set #high example_var 62
scoreboard players set #mid example_var 4
scoreboard players set #2 example_var 2
data modify storage bl_example targetY set value 4i
execute store result score #result example_var run function bl_example:binary_search/ocean_floor_height with storage bl_example
tellraw @s ["Ocean depth: ",{"score":{"name":"#result","objective":"example_var"}}]