from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship, Mapped, mapped_column
from .database import Base

def now(): return datetime.now(timezone.utc)

class Mission(Base):
    __tablename__ = "missions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="PLANNED")
    phase: Mapped[str] = mapped_column(String(30), default="EARTH_PREPARATION")
    start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    astronauts = relationship("Astronaut", back_populates="mission")

class Astronaut(Base):
    __tablename__ = "astronauts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    call_sign: Mapped[str] = mapped_column(String(40), unique=True)
    role: Mapped[str] = mapped_column(String(80), default="Crew member")
    mission_id: Mapped[int | None] = mapped_column(ForeignKey("missions.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    mission = relationship("Mission", back_populates="astronauts")
    readings = relationship("HealthReading", back_populates="astronaut", cascade="all, delete-orphan")

class HealthReading(Base):
    __tablename__ = "readings"
    id: Mapped[int] = mapped_column(primary_key=True)
    astronaut_id: Mapped[int] = mapped_column(ForeignKey("astronauts.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    spo2: Mapped[float | None] = mapped_column(Float, nullable=True)
    systolic: Mapped[float | None] = mapped_column(Float, nullable=True)
    diastolic: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity: Mapped[str] = mapped_column(String(30))
    phase: Mapped[str] = mapped_column(String(30))
    environment: Mapped[str] = mapped_column(String(10))
    sensor_source: Mapped[str] = mapped_column(String(80), default="SIMULATED")
    sensor_quality: Mapped[str] = mapped_column(String(20), default="VALID")
    status: Mapped[str] = mapped_column(String(20), default="RECORDED")
    astronaut = relationship("Astronaut", back_populates="readings")

class EarthBaseline(Base):
    __tablename__ = "baselines"
    id: Mapped[int] = mapped_column(primary_key=True)
    astronaut_id: Mapped[int] = mapped_column(ForeignKey("astronauts.id"))
    activity: Mapped[str] = mapped_column(String(30))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sample_count: Mapped[int] = mapped_column(Integer)
    statistics_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    astronaut = relationship("Astronaut")
    approval = relationship("BaselineApproval", back_populates="baseline", uselist=False)

class BaselineApproval(Base):
    __tablename__ = "baseline_approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    baseline_id: Mapped[int] = mapped_column(ForeignKey("baselines.id"))
    reviewer: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(20))
    comments: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    baseline = relationship("EarthBaseline", back_populates="approval")

class HealthAssessment(Base):
    __tablename__ = "assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    reading_id: Mapped[int] = mapped_column(ForeignKey("readings.id"))
    baseline_id: Mapped[int | None] = mapped_column(ForeignKey("baselines.id"), nullable=True)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class HealthAlert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"))
    astronaut_id: Mapped[int] = mapped_column(ForeignKey("astronauts.id"))
    severity: Mapped[str] = mapped_column(String(30))
    explanation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    comments: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(30), default="RESEARCHER")
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class SyncRecord(Base):
    __tablename__ = "sync_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_request_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    reading_id: Mapped[int] = mapped_column(ForeignKey("readings.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class UserNotification(Base):
    __tablename__ = "user_notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    href: Mapped[str] = mapped_column(String(240), default="/medical-review.html")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
