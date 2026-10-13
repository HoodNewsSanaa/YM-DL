from __future__ import annotations

import multiprocessing


if __name__ == "__main__":
    multiprocessing.freeze_support()
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        from selfcheck import run
        run(sys.argv[2])
    else:
        from gui import main
        main()
