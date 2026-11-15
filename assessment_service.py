import json
from sqlalchemy import select
from ..config import DEVIATION_THRESHOLD
from ..models import EarthBaseline, HealthAssessment, HealthAlert, User, UserNotification
from .baseline_service import PARAMETERS

def assess(db, reading):
    outcome = {"reading_id": reading.id, "comparison_available": False, "message": "Baseline not approved. Generate and approve a matching activity baseline first.", "metrics": [], "severity": "INFORMATION"}
    baseline = db.scalar(select(EarthBaseline).where(EarthBaseline.astronaut_id == reading.astronaut_id,
            EarthBaseline.activity == reading.activity, EarthBaseline.status == "APPROVED").order_by(EarthBaseline.version.desc()))
    if reading.sensor_quality == "INVALID":
        outcome["message"] = "Sensor quality is INVALID. This record is not used as a reliable assessment."
    elif reading.environment != "SPACE":
        outcome["message"] = "Assessment is available for space readings only."
    elif reading.sensor_quality == "QUESTIONABLE":
        outcome["message"] = "Sensor quality is QUESTIONABLE. Review the measurement before interpreting it."
    elif baseline:
        outcome.update(comparison_available=True, baseline_id=baseline.id,
                       message="Compared with the approved personal baseline for the same activity.")
        stats = json.loads(baseline.statistics_json)
        flags = []
        for key in PARAMETERS:
            value, item = getattr(reading, key), stats.get(key)
            if value is None or not item: continue
            sd = item["std_dev"]
            z = (value-item["mean"])/sd if sd else (0.0 if value == item["mean"] else None)
            flagged = abs(z) >= DEVIATION_THRESHOLD if z is not None else value != item["mean"]
            metric = {"parameter":key,"observed":value,"mean":item["mean"],"std_dev":sd,"z_score":z,"flagged":flagged}
            outcome["metrics"].append(metric)
            if flagged: flags.append(metric)
        if flags:
            outcome["severity"] = "REVIEW_REQUIRED"
            names = ", ".join(x["parameter"].replace("_", " ") for x in flags)
            outcome["message"] = f"{names} differed from the personal baseline by the illustrative threshold (|z| ≥ {DEVIATION_THRESHOLD:g}). Review is suggested; this is not a diagnosis."
    assessment = HealthAssessment(reading_id=reading.id, baseline_id=outcome.get("baseline_id"), result_json=json.dumps(outcome))
    db.add(assessment); db.flush()
    if outcome["severity"] == "REVIEW_REQUIRED":
        alert=HealthAlert(assessment_id=assessment.id, astronaut_id=reading.astronaut_id,
                          severity=outcome["severity"], explanation=outcome["message"])
        db.add(alert); db.flush()
        for reviewer in db.scalars(select(User).where(User.active.is_(True),User.role.in_(("ADMINISTRATOR","MEDICAL_OFFICER")))).all():
            db.add(UserNotification(user_id=reviewer.id,title="Health reading flagged for review",
                  message=outcome["message"],href="/medical-review.html"))
    db.commit(); outcome["assessment_id"] = assessment.id
    return outcome
