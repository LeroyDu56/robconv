"""Entry point of the desktop application (robconv.exe).

    robconv.exe                      opens the window
    robconv.exe <backup or files>    what Windows passes when items are dropped on the icon:
                                     the window opens and converts them right away

ROBCONV_NO_GUI=1 runs the same conversion without a window (used to smoke-test the exe).
"""

import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    paths = [Path(p) for p in (sys.argv[1:] if argv is None else argv)]
    if os.environ.get("ROBCONV_NO_GUI") == "1":
        from robconv import pipeline

        result = pipeline.run(paths)
        print(f"{result.programs} programs, {result.todo} TODO -> {result.folder}")
        return 0

    from robconv.gui import launch

    launch(paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
