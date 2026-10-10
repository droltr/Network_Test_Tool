# Kept for existing instructions and scripts: the build is now OS-independent.
# Use `python build.py` on any OS; see README.md -> Building.

import runpy

if __name__ == "__main__":
    runpy.run_path("build.py", run_name="__main__")
