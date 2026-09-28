# Compiled by Blocklight 1.0.dev (https://github.com/qcjames53/blocklight)
# Changes saved to this file will not persist. Please modify the bl source file instead:
#     `data/bl_example/blocklight/binary_search.bl:3`
scoreboard players set #_bl_returning _bl 0
execute if score #low example_var > #high example_var run function bl_example:binary_search/ocean_floor_height_helper/chain_0_if
execute if score #_bl_returning _bl matches 1 if score #_bl_return_success _bl matches 1 run return run scoreboard players get #_bl_return_value _bl
execute if score #_bl_returning _bl matches 1 if score #_bl_return_success _bl matches 0 run return fail
$execute positioned ~ $(targetY) ~ run function bl_example:binary_search/ocean_floor_height_helper/positioned_0 {"targetY": "$(targetY)"}
execute if score #_bl_returning _bl matches 1 if score #_bl_return_success _bl matches 1 run return run scoreboard players get #_bl_return_value _bl
execute if score #_bl_returning _bl matches 1 if score #_bl_return_success _bl matches 0 run return fail
scoreboard players operation #mid example_var = #high example_var
scoreboard players operation #mid example_var -= #low example_var
scoreboard players operation #mid example_var /= #2 example_var
scoreboard players operation #mid example_var += #low example_var
execute store result storage bl_example targetY int 1 run scoreboard players get #mid example_var
scoreboard players set #_bl_returning _bl 1
execute store result score #_bl_return_value _bl store success score #_bl_return_success _bl run return run function bl_example:binary_search/ocean_floor_height with storage bl_example