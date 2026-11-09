"""Run this input set with one tanker and one scooper; accept runner overrides."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from integration_v2.run_dynamic import main


if __name__ == "__main__":
    raise SystemExit(main([
        "--landscape", str(HERE / "landscape.tif"),
        "--ignition", str(HERE / "ignition.shp"),
        "--native-config", str(HERE / "native_settings.json"),
        "--output-dir", str(HERE.parents[1] / "outputs" / "growing_fire"),
        "--tankers", "1", "--scoopers", "1",
        "--airfield", "11", "0", "--water-cell", "11", "11",
        "--horizon", "6", "--commit", "2", "--total-steps", "16",
        "--step-minutes", "1", "--time-limit", "20",
        "--wind-speed", "10", "--wind-speed-std", "0",
        "--wind-from", "225", "--wind-dir-std", "0",
        *sys.argv[1:],
    ]))
