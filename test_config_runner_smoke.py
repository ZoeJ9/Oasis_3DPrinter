"""Smoke test: 1 step x 2 layers, no printer hardware required."""
import os, tempfile, csv
from config_runner import ConfigRunner

CSV = """step_id,layers,print_speed,travel_speed,layer_thickness,dpi,density,preheat,prime,layer_passes,overfeed,note
1,2,2200,3000,0.1,300,250,1,15,3,2.5,smoke_test
"""

with tempfile.TemporaryDirectory() as tmp:
    csv_path = os.path.join(tmp, "print_config.csv")
    with open(csv_path, "w") as f:
        f.write(CSV)

    runner = ConfigRunner(csv_path, main_window=None)   # no hardware
    runner.run()                                         # prints to stdout

    log_path = os.path.join(tmp, "config_log.csv")
    with open(log_path) as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 4, f"Expected 4 log rows (2 layers x pre+post), got {len(rows)}"
    assert rows[0]["pre_or_post"] == "pre"
    assert rows[1]["pre_or_post"] == "post"
    assert rows[0]["image_filename"].startswith("s001_L000_pre_")
    print("Smoke test PASSED — 4 log rows written correctly.")
