"""Enable ``python -m dir3 <planfile>``."""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
