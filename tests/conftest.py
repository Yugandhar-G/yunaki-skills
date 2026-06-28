"""Make recall.py / binder.py importable as top-level modules (folder has hyphens)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
