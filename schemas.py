from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, AliasChoices

class MissionIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    status: str = "PLANNED"
    phase: str = "EARTH_PREPARATION"
    start_date: str | None = None
    end_date: str | None = None
    description: str = ""
class AstronautIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    call_sign: str = Field(min_length=2, max_length=40)
    role: str = "Crew member"
    mission_id: int | None = None
class ReadingIn(BaseModel):
    astronaut_id: int
    timestamp: datetime | None = Field(default=None, validation_alias=AliasChoices("timestamp","recorded_at"))
    client_request_id: str | None = Field(default=None, max_length=64)
    heart_rate: float | None = Field(default=None, ge=20, le=240)
    spo2: float | None = Field(default=None, ge=50, le=100)
    systolic: float | None = Field(default=None, ge=50, le=260, validation_alias=AliasChoices("systolic","systolic_bp"))
    diastolic: float | None = Field(default=None, ge=30, le=180, validation_alias=AliasChoices("diastolic","diastolic_bp"))
    activity: str = "RESTING"
    phase: str = Field(default="EARTH_PREPARATION", validation_alias=AliasChoices("phase","mission_phase"))
    environment: str = "EARTH"
    sensor_source: str = "SIMULATED"
    sensor_quality: str = Field(default="VALID", validation_alias=AliasChoices("sensor_quality","quality_status"))
class ReviewIn(BaseModel):
    reviewer: str = "Simulated reviewer"
    decision: str = "APPROVED"
    comments: str = ""
class AlertReviewIn(BaseModel):
    status: str = "ACKNOWLEDGED"
    comments: str = ""
class BootstrapIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)
class LoginIn(BaseModel):
    email: str
    password: str
class UserCreateIn(BootstrapIn):
    role: str = "RESEARCHER"
class UserAdminUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    role: str | None = None
    active: bool | None = None
class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)
