"""测试共享的场景构造。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from basin_review.demo import build_demo_service  # noqa: F401
