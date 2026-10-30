# Compiled by Blocklight 1.1 (https://github.com/qcjames53/blocklight)
# Changes saved to this file will not persist. Please modify the bl source file instead:
#     `data/bl_example/blocklight/functions.bl:31`
execute as @p run function bl_example:functions/return_0_helper/as_0
execute if score #_bl_returning _bl matches 1 run return run function bl_example:functions/return_0_helper/return_handler
say This will never run.