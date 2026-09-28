# Compiled by Blocklight 1.0.dev (https://github.com/qcjames53/blocklight)
# Changes saved to this file will not persist. Please modify the bl source file instead:
#     `data/bl_example/blocklight/functions.bl:31`
scoreboard players set #_bl_returning _bl 0
execute as @p run function bl_example:functions/return_0_helper/as_0
execute if score #_bl_returning _bl matches 1 if score #_bl_return_success _bl matches 1 run return run scoreboard players get #_bl_return_value _bl
execute if score #_bl_returning _bl matches 1 if score #_bl_return_success _bl matches 0 run return fail
say This will never run.