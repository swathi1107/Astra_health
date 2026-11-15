import json, statistics
from sqlalchemy import select
from ..models import HealthReading, EarthBaseline

PARAMETERS = ("heart_rate", "spo2", "systolic", "diastolic")

def generate_baseline(db, astronaut_id: int, activity: str):
    readings = db.scalars(select(HealthReading).where(
        HealthReading.astronaut_id == astronaut_id,
        HealthReading.activity == activity,
        HealthReading.environment == "EARTH",
        HealthReading.sensor_quality == "VALID",
    )).all()
    if len(readings) < 5:
        raise ValueError(f"At least 5 valid Earth readings for {activity} are required; found {len(readings)}.")
    stats = {}
    for key in PARAMETERS:
        values = [getattr(r, key) for r in readings if getattr(r, key) is not None]
        if values:
            stats[key] = {"mean": statistics.mean(values), "median": statistics.median(values),
                          "std_dev": statistics.stdev(values) if len(values) > 1 else 0,
                          "min": min(values), "max": max(values), "count": len(values)}
    versions = db.scalars(select(EarthBaseline).where(EarthBaseline.astronaut_id == astronaut_id,
                          EarthBaseline.activity == activity)).all()
    baseline = EarthBaseline(astronaut_id=astronaut_id, activity=activity,
        version=max([v.version for v in versions], default=0)+1, sample_count=len(readings),
        statistics_json=json.dumps(stats), status="PENDING")
    db.add(baseline); db.commit(); db.refresh(baseline)
    return baseline
