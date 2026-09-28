# Compiled by Blocklight 1.0.dev (https://github.com/qcjames53/blocklight)
# Changes saved to this file will not persist. Please modify the bl source file instead:
#     `data/bl_example/blocklight/binary_search.bl:7`
$execute unless block ~ ~ ~ minecraft:water if block ~ ~1 ~ minecraft:water run function bl_example:binary_search/ocean_floor_height_helper/positioned_0_helper/chain_0_if {"targetY": "$(targetY)"}
execute if score #_bl_returning _bl matches 1 run return 0
execute unless block ~ ~ ~ minecraft:water run function bl_example:binary_search/ocean_floor_height_helper/positioned_0_helper/chain_1_if
execute if block ~ ~ ~ minecraft:water run function bl_example:binary_search/ocean_floor_height_helper/positioned_0_helper/chain_2_if