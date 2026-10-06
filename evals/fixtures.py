"""Fixed FACTS fixtures for evaluating LLM grounding. Add a case whenever you see a bad reply."""
RUN_EASY = {
    "kind": "run", "name": "Morning run", "date": "2026-10-03", "distance_km": 10.02,
    "duration_min": 52.1, "avg_pace_per_km": "5:12", "avg_hr": 148, "max_hr_used_for_zones": 190,
    "zone_pct": {"Z1": 8.0, "Z2": 71.5, "Z3": 17.0, "Z4": 3.5, "Z5": 0.0},
    "decoupling_pct": 3.4, "trimp": 71.2, "acwr": 1.12, "acwr_label": "sweet spot",
    "vs_recent": {"compared_runs": 4, "pace_vs_median_sec_per_km": -6, "avg_hr_vs_median_bpm": -2,
                  "efficiency_change_pct": 3.1},
    "laps": [{"n": 1, "distance_km": 1.0, "pace_per_km": "5:20", "avg_hr": 140}],
}
RUN_DRIFT = dict(RUN_EASY, name="Long run", distance_km=21.1, duration_min=121.0,
                 avg_pace_per_km="5:44", avg_hr=158, decoupling_pct=9.2, acwr=1.62,
                 acwr_label="high injury-risk zone", vs_recent=None,
                 zone_pct={"Z1": 2.0, "Z2": 40.0, "Z3": 41.0, "Z4": 15.0, "Z5": 2.0})
RUN_NO_DATA = {"kind": "run", "name": "Treadmill", "date": "2026-10-04", "distance_km": 5.0,
               "duration_min": 30.0, "avg_pace_per_km": "6:00", "avg_hr": 0,
               "zone_pct": {"Z1": 0, "Z2": 0, "Z3": 0, "Z4": 0, "Z5": 0}, "decoupling_pct": None,
               "trimp": 0.0, "acwr": None, "acwr_label": "not enough history", "vs_recent": None}
LIFT_PR = {
    "kind": "strength", "name": "Push Day", "date": "2026-10-05", "total_volume_kg": 5120.0,
    "total_sets": 14, "plateaued_lifts": [],
    "prs": [{"exercise": "Bench Press", "new_e1rm_kg": 105.0, "previous_e1rm_kg": 101.7,
             "improvement_kg": 3.3, "set": "90kg x 5"}],
    "exercises": [{"name": "Bench Press", "sets": 5, "reps": 25, "volume_kg": 2250.0,
                   "top_e1rm_kg": 105.0, "best_set": "90kg x 5"},
                  {"name": "Overhead Press", "sets": 4, "reps": 32, "volume_kg": 1280.0,
                   "top_e1rm_kg": 52.0, "best_set": "40kg x 8"}],
}
LIFT_PLATEAU = dict(LIFT_PR, name="Pull Day", prs=[], plateaued_lifts=["Barbell Row"])

ALL = {"run_easy": RUN_EASY, "run_drift": RUN_DRIFT, "run_no_data": RUN_NO_DATA,
       "lift_pr": LIFT_PR, "lift_plateau": LIFT_PLATEAU}
