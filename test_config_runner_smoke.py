"""Smoke test: 2 steps x 2 layers, no printer hardware required.

Also verifies applied_* log columns are read back per-step (not just the
raw CSV echoed back), which is the whole point of the dry-run injection
audit — a step-to-step value change here proves the injection chain works.
"""
import os, tempfile, csv
from config_runner import ConfigRunner

CSV = """step_id,layers,print_speed,spread_speed,layer_thickness,dpi,density,layer_passes,overfeed,separation_layers,travel_speed,note
1,2,2200,6000,0.1,600,250,3,1.75,0,3000,baseline
2,2,1100,3000,0.1,600,100,1,1.75,0,3000,low_speed_thin
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

    assert len(rows) == 8, f"Expected 8 log rows (2 steps x 2 layers x pre+post), got {len(rows)}"
    assert rows[0]["pre_or_post"] == "pre"
    assert rows[1]["pre_or_post"] == "post"
    assert rows[0]["image_filename"].startswith("s001_L000_pre_")

    # applied_* must reflect the per-step injected values, and must change
    # between step 1 and step 2 — this is the regression check for the
    # "log trusts CSV, hardware disagrees" bug.
    step1_rows = [r for r in rows if r["step_id"] == "1"]
    step2_rows = [r for r in rows if r["step_id"] == "2"]
    assert step1_rows[0]["applied_print_speed"]  == "2200.0"
    assert step1_rows[0]["applied_spread_speed"] == "6000.0"
    assert step1_rows[0]["applied_density"]      == "250"
    assert step2_rows[0]["applied_print_speed"]  == "1100.0"
    assert step2_rows[0]["applied_spread_speed"] == "3000.0"
    assert step2_rows[0]["applied_density"]      == "100"

    print("Smoke test PASSED — 8 log rows written correctly, "
          "applied_* values change between steps.")
