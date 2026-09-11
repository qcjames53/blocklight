# Helpers for unit test suite

import blocklight

NO_HEADER = blocklight.CompilerOptions(no_header=True)


def compile_source(
    source: str,
    *,
    local_path: str = "data/pack/blocklight/main.bl",
    options: blocklight.CompilerOptions = NO_HEADER,
    pack_name: str | None = None,
    pack_format: int | None = None,
    namespace: str | None = None,
) -> blocklight.CompiledOutput:
    out = blocklight.CompiledOutput()
    sf = blocklight.SourceFile(
        local_path=local_path,
        source=source,
        pack_name=pack_name,
        pack_format=pack_format,
        namespace=namespace,
    )
    blocklight.compile_file(sf, out, options)
    return out
