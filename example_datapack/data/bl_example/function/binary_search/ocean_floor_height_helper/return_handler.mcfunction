# Compiled by Blocklight 1.0.dev (https://github.com/qcjames53/blocklight)
# Changes saved to this file will not persist. Please modify the bl source file instead:
#     `data/bl_example/blocklight/binary_search.bl:3`
scoreboard players set #_bl_returning _bl 0
execute if score #_bl_return_success _bl matches 0 run return fail
return run scoreboard players get #_bl_return_value _bl