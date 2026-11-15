import csv, hashlib, io, json, random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Query, Header, Cookie, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .database import Base, engine, get_db
from . import models as m
from .schemas import MissionIn, AstronautIn, ReadingIn, ReviewIn, AlertReviewIn
from .services.baseline_service import generate_baseline
from .services.assessment_service import assess
from .schemas import BootstrapIn, LoginIn, UserCreateIn, UserAdminUpdate, PasswordChangeIn
from .security import current_user, require_roles, hash_password, verify_password, new_session

Base.metadata.create_all(bind=engine)
app = FastAPI(title="ASTRA HEALTH", description="Offline-first personal-baseline decision-support prototype. Not a diagnostic system.", version="1.0.0")
FRONT = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONT), name="static")

def dump(obj):
    data = {c.name:getattr(obj,c.name) for c in obj.__table__.columns}
    for k,v in data.items():
        if isinstance(v, datetime): data[k]=v.isoformat()
    if isinstance(obj,m.HealthReading):
        data.update({"recorded_at":data["timestamp"],"systolic_bp":data["systolic"],
                     "diastolic_bp":data["diastolic"],"mission_phase":data["phase"],
                     "quality_status":data["sensor_quality"]})
    return data

@app.get("/", include_in_schema=False)
def home(): return FileResponse(FRONT/"index.html")
@app.get("/{page}.html", include_in_schema=False)
def pages(page: str):
    path=FRONT/f"{page}.html"
    if path.exists(): return FileResponse(path)
    raise HTTPException(404,"Page not found")
@app.get("/manifest.json", include_in_schema=False)
def manifest(): return FileResponse(FRONT/"manifest.json")
@app.get("/service-worker.js", include_in_schema=False)
def sw(): return FileResponse(FRONT/"service-worker.js", media_type="application/javascript")
@app.get("/api/health")
def health(): return {"status":"ok","service":"ASTRA HEALTH","database":"connected"}

def audit(db, user, action, entity, entity_id=None, detail=""):
    db.add(m.AuditLog(user_id=user.id if user else None, action=action, entity=entity,
                      entity_id=str(entity_id) if entity_id is not None else None, detail=detail))

def notify_roles(db,roles,title,message,href="/medical-review.html"):
    recipients=db.scalars(select(m.User).where(m.User.active.is_(True),m.User.role.in_(roles))).all()
    for recipient in recipients:
        db.add(m.UserNotification(user_id=recipient.id,title=title,message=message,href=href))

@app.get("/api/auth/setup-status")
def setup_status(db:Session=Depends(get_db)):
    count=db.scalar(select(func.count(m.User.id))) or 0
    return {"needs_admin": count == 0}

@app.post("/api/auth/bootstrap")
def bootstrap(data:BootstrapIn,response:Response,db:Session=Depends(get_db)):
    if (db.scalar(select(func.count(m.User.id))) or 0) > 0:
        raise HTTPException(409,"Initial administrator is already configured.")
    email=data.email.strip().lower()
    if "@" not in email or "." not in email.rsplit("@",1)[-1]: raise HTTPException(422,"Enter a valid email address.")
    user=m.User(email=email,full_name=data.full_name.strip(),role="ADMINISTRATOR",password_hash=hash_password(data.password))
    db.add(user); db.flush(); audit(db,user,"INITIAL_ADMIN_CREATED","User",user.id,"First-run account setup")
    token,expires=new_session(db,user); db.commit()
    response.set_cookie("astra_session",token,httponly=True,samesite="strict",secure=False,max_age=36000,path="/")
    return {"expires_at":expires.isoformat(),"user":{"id":user.id,"email":user.email,"full_name":user.full_name,"role":user.role}}

@app.post("/api/auth/login")
def login(data:LoginIn,response:Response,db:Session=Depends(get_db)):
    user=db.scalar(select(m.User).where(m.User.email==data.email.strip().lower()))
    if not user or not user.active or not verify_password(data.password,user.password_hash):
        raise HTTPException(401,"Email or password was not recognised.")
    token,expires=new_session(db,user); audit(db,user,"LOGIN","User",user.id)
    db.commit()
    response.set_cookie("astra_session",token,httponly=True,samesite="strict",secure=False,max_age=36000,path="/")
    return {"expires_at":expires.isoformat(),"user":{"id":user.id,"email":user.email,"full_name":user.full_name,"role":user.role}}

@app.get("/api/auth/me")
def me(user:m.User=Depends(current_user)):
    return {"id":user.id,"email":user.email,"full_name":user.full_name,"role":user.role}

@app.post("/api/auth/logout")
def logout(response:Response,astra_session:str|None=Cookie(default=None),user:m.User=Depends(current_user),db:Session=Depends(get_db)):
    raw=astra_session or ""; token_hash=hashlib.sha256(raw.encode()).hexdigest()
    session=db.scalar(select(m.AuthSession).where(m.AuthSession.token_hash==token_hash))
    if session: db.delete(session)
    audit(db,user,"LOGOUT","User",user.id); db.commit()
    response.delete_cookie("astra_session",path="/",samesite="strict")
    return {"logged_out":True}

@app.post("/api/auth/password")
def change_password(data:PasswordChangeIn,response:Response,astra_session:str|None=Cookie(default=None),user:m.User=Depends(current_user),db:Session=Depends(get_db)):
    if not verify_password(data.current_password,user.password_hash): raise HTTPException(400,"Current password was not recognised.")
    if data.current_password==data.new_password: raise HTTPException(422,"Choose a new password different from the current one.")
    user.password_hash=hash_password(data.new_password)
    db.query(m.AuthSession).filter(m.AuthSession.user_id==user.id).delete(synchronize_session=False)
    token,expires=new_session(db,user); audit(db,user,"PASSWORD_CHANGED","User",user.id); db.commit()
    response.set_cookie("astra_session",token,httponly=True,samesite="strict",secure=False,max_age=36000,path="/")
    return {"updated":True,"expires_at":expires.isoformat()}

@app.get("/api/users")
def users(db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR"))):
    return [{"id":x.id,"email":x.email,"full_name":x.full_name,"role":x.role,"active":x.active,"created_at":x.created_at.isoformat()} for x in db.scalars(select(m.User).order_by(m.User.id)).all()]

@app.post("/api/users")
def create_user(data:UserCreateIn,db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR"))):
    role=data.role.upper()
    if role not in {"ADMINISTRATOR","MEDICAL_OFFICER","RESEARCHER","ASTRONAUT"}: raise HTTPException(422,"Choose a supported account role.")
    email=data.email.strip().lower()
    if "@" not in email or "." not in email.rsplit("@",1)[-1]: raise HTTPException(422,"Enter a valid email address.")
    x=m.User(email=email,full_name=data.full_name.strip(),role=role,password_hash=hash_password(data.password))
    db.add(x)
    try: db.flush(); audit(db,user,"USER_CREATED","User",x.id,f"role={role}"); db.commit(); db.refresh(x)
    except Exception: db.rollback(); raise HTTPException(409,"An account already uses this email.")
    return {"id":x.id,"email":x.email,"full_name":x.full_name,"role":x.role,"active":x.active}

@app.put("/api/users/{user_id}")
def update_user(user_id:int,data:UserAdminUpdate,db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR"))):
    target=db.get(m.User,user_id)
    if not target: raise HTTPException(404,"Account not found")
    changes=data.model_dump(exclude_unset=True)
    if target.id==user.id and changes.get("active") is False: raise HTTPException(422,"You cannot deactivate your own account.")
    if changes.get("role") and changes["role"].upper() not in {"ADMINISTRATOR","MEDICAL_OFFICER","RESEARCHER","ASTRONAUT"}:
        raise HTTPException(422,"Choose a supported account role.")
    if target.role=="ADMINISTRATOR" and changes.get("active") is False:
        admins=db.scalar(select(func.count(m.User.id)).where(m.User.role=="ADMINISTRATOR",m.User.active.is_(True))) or 0
        if admins<=1: raise HTTPException(409,"Keep at least one active Administrator account.")
    for key,value in changes.items(): setattr(target,key,value.upper() if key=="role" and value else value)
    if target.active is False: db.query(m.AuthSession).filter(m.AuthSession.user_id==target.id).delete(synchronize_session=False)
    audit(db,user,"USER_UPDATED","User",target.id,json.dumps(changes)); db.commit()
    return {"id":target.id,"email":target.email,"full_name":target.full_name,"role":target.role,"active":target.active}

@app.get("/api/notifications")
def notifications(db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    rows=db.scalars(select(m.UserNotification).where(m.UserNotification.user_id==user.id).order_by(m.UserNotification.created_at.desc()).limit(100)).all()
    return [{**dump(x),"unread":x.read_at is None} for x in rows]

@app.post("/api/notifications/{notification_id}/read")
def notification_read(notification_id:int,db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    item=db.scalar(select(m.UserNotification).where(m.UserNotification.id==notification_id,m.UserNotification.user_id==user.id))
    if not item: raise HTTPException(404,"Notification not found")
    item.read_at=datetime.now(timezone.utc); db.commit(); return {**dump(item),"unread":False}

@app.post("/api/notifications/read-all")
def notifications_read_all(db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    rows=db.scalars(select(m.UserNotification).where(m.UserNotification.user_id==user.id,m.UserNotification.read_at.is_(None))).all()
    now=datetime.now(timezone.utc)
    for item in rows: item.read_at=now
    db.commit(); return {"marked_read":len(rows)}

@app.get("/api/missions")
def missions(db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    return [{**dump(x),"astronaut_count":len(x.astronauts)} for x in db.scalars(select(m.Mission).order_by(m.Mission.id.desc())).all()]
@app.post("/api/missions")
def create_mission(data:MissionIn,db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR","RESEARCHER"))):
    x=m.Mission(**data.model_dump()); db.add(x)
    try: db.flush(); audit(db,user,"MISSION_CREATED","Mission",x.id); notify_roles(db,("ADMINISTRATOR","RESEARCHER"),"Mission created",f"Mission {x.name} is available.","/missions.html"); db.commit(); db.refresh(x)
    except Exception: db.rollback(); raise HTTPException(409,"Mission name already exists.")
    return dump(x)
@app.put("/api/missions/{mid}")
def update_mission(mid:int,data:MissionIn,db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR","RESEARCHER"))):
    x=db.get(m.Mission,mid)
    if not x: raise HTTPException(404,"Mission not found")
    for k,v in data.model_dump().items(): setattr(x,k,v)
    db.commit(); db.refresh(x); return dump(x)
@app.delete("/api/missions/{mid}")
def delete_mission(mid:int,db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR"))):
    x=db.get(m.Mission,mid)
    if not x: raise HTTPException(404,"Mission not found")
    if x.astronauts: raise HTTPException(409,"Reassign astronauts before deleting this mission.")
    db.delete(x); db.commit(); return {"deleted":True}

@app.get("/api/astronauts")
def astronauts(db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    rows=db.scalars(select(m.Astronaut).order_by(m.Astronaut.id.desc())).all()
    return [{**dump(x),"mission_name":x.mission.name if x.mission else None,"reading_count":len(x.readings)} for x in rows]
@app.post("/api/astronauts")
def create_astronaut(data:AstronautIn,db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR","RESEARCHER"))):
    if data.mission_id and not db.get(m.Mission,data.mission_id): raise HTTPException(404,"Mission not found")
    x=m.Astronaut(**data.model_dump()); db.add(x)
    try: db.commit(); db.refresh(x)
    except Exception: db.rollback(); raise HTTPException(409,"Call sign already exists.")
    return dump(x)
@app.put("/api/astronauts/{aid}")
def update_astronaut(aid:int,data:AstronautIn,db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR","RESEARCHER"))):
    x=db.get(m.Astronaut,aid)
    if not x: raise HTTPException(404,"Astronaut not found")
    for k,v in data.model_dump().items(): setattr(x,k,v)
    db.commit(); db.refresh(x); return dump(x)
@app.get("/api/astronauts/{aid}")
def profile(aid:int,db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    x=db.get(m.Astronaut,aid)
    if not x: raise HTTPException(404,"Astronaut not found")
    return {**dump(x),"mission_name":x.mission.name if x.mission else None,"readings":[dump(r) for r in x.readings]}

@app.get("/api/readings")
def readings(astronaut_id:int|None=None,activity:str|None=None,environment:str|None=None,phase:str|None=None,
            from_date:datetime|None=None,to_date:datetime|None=None,db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    q=select(m.HealthReading).order_by(m.HealthReading.timestamp.desc())
    for col,val in ((m.HealthReading.astronaut_id,astronaut_id),(m.HealthReading.activity,activity),(m.HealthReading.environment,environment),(m.HealthReading.phase,phase)):
        if val is not None: q=q.where(col==val)
    if from_date is not None: q=q.where(m.HealthReading.timestamp>=from_date)
    if to_date is not None: q=q.where(m.HealthReading.timestamp<=to_date)
    return [dump(x) for x in db.scalars(q.limit(500)).all()]
@app.post("/api/readings")
def create_reading(data:ReadingIn,db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    if not db.get(m.Astronaut,data.astronaut_id): raise HTTPException(404,"Astronaut not found")
    if data.activity not in {"RESTING","SLEEPING","WALKING","EXERCISE","WORKING","OTHER"}: raise HTTPException(422,"Unsupported activity")
    if data.environment not in {"EARTH","SPACE"} or data.sensor_quality not in {"VALID","QUESTIONABLE","INVALID"}: raise HTTPException(422,"Invalid environment or sensor quality")
    if data.client_request_id:
        synced=db.scalar(select(m.SyncRecord).where(m.SyncRecord.client_request_id==data.client_request_id))
        if synced:
            old=db.get(m.HealthReading,synced.reading_id)
            return {"reading":dump(old),"sync_status":"already_synchronized","duplicate":True}
    d=data.model_dump(exclude={"client_request_id"}); d["timestamp"]=d["timestamp"] or datetime.now(timezone.utc)
    x=m.HealthReading(**d); db.add(x); db.flush()
    if data.client_request_id:
        db.add(m.SyncRecord(client_request_id=data.client_request_id,reading_id=x.id))
    db.commit(); db.refresh(x)
    result={"reading":dump(x)}
    if x.environment=="SPACE": result["assessment"]=assess(db,x)
    result["sync_status"]="synchronized"
    return result

@app.get("/api/baselines")
def baselines(db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    return [{**dump(x),"statistics":json.loads(x.statistics_json),"astronaut_name":x.astronaut.name,"review":dump(x.approval) if x.approval else None} for x in db.scalars(select(m.EarthBaseline).order_by(m.EarthBaseline.id.desc())).all()]
@app.post("/api/baselines/generate")
def baseline_generate(astronaut_id:int,activity:str="RESTING",db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR","MEDICAL_OFFICER","RESEARCHER"))):
    if not db.get(m.Astronaut,astronaut_id): raise HTTPException(404,"Astronaut not found")
    try:
        x=generate_baseline(db,astronaut_id,activity)
        audit(db,user,"BASELINE_GENERATED","Baseline",x.id,f"activity={activity}")
        notify_roles(db,("ADMINISTRATOR","MEDICAL_OFFICER"),"Personal baseline awaiting review",f"A new {activity} Earth baseline is pending review.")
        db.commit(); return dump(x)
    except ValueError as e: raise HTTPException(422,str(e))
@app.post("/api/baselines/{bid}/review")
def baseline_review(bid:int,data:ReviewIn,db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR","MEDICAL_OFFICER"))):
    x=db.get(m.EarthBaseline,bid)
    if not x: raise HTTPException(404,"Baseline not found")
    if x.status!="PENDING": raise HTTPException(409,"Only pending baselines can be reviewed.")
    if data.decision not in {"APPROVED","REJECTED"}: raise HTTPException(422,"Decision must be APPROVED or REJECTED")
    x.status=data.decision; approval=m.BaselineApproval(baseline_id=x.id,reviewer=user.full_name,decision=data.decision,comments=data.comments)
    db.add(approval); audit(db,user,"BASELINE_REVIEWED","Baseline",x.id,f"decision={data.decision}"); db.commit(); db.refresh(x); return {**dump(x),"review":dump(approval)}

@app.get("/api/alerts")
def alerts(db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    rows=db.scalars(select(m.HealthAlert).order_by(m.HealthAlert.created_at.desc())).all()
    result=[]
    for a in rows:
        ass=db.get(m.HealthAssessment,a.assessment_id); r=db.get(m.HealthReading,ass.reading_id) if ass else None
        result.append({**dump(a),"astronaut_name":db.get(m.Astronaut,a.astronaut_id).name,"reading":dump(r) if r else None,"assessment":json.loads(ass.result_json) if ass else {}})
    return result
@app.post("/api/alerts/{alert_id}/review")
def alert_review(alert_id:int,data:AlertReviewIn,db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR","MEDICAL_OFFICER"))):
    a=db.get(m.HealthAlert,alert_id)
    if not a: raise HTTPException(404,"Alert not found")
    if data.status not in {"ACKNOWLEDGED","RESOLVED"}: raise HTTPException(422,"Status must be ACKNOWLEDGED or RESOLVED")
    a.status=data.status; a.comments=data.comments; audit(db,user,"ALERT_REVIEWED","Alert",a.id,f"status={data.status}"); db.commit(); return dump(a)

@app.get("/api/history")
def history(astronaut_id:int|None=None,db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    q=select(m.HealthReading).order_by(m.HealthReading.timestamp.desc())
    if astronaut_id: q=q.where(m.HealthReading.astronaut_id==astronaut_id)
    return [{**dump(r),"astronaut_name":r.astronaut.name} for r in db.scalars(q.limit(1000)).all()]
@app.get("/api/assessments")
def assessment_history(db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    rows=db.scalars(select(m.HealthAssessment).order_by(m.HealthAssessment.created_at.desc())).all()
    return [{**dump(x),"result":json.loads(x.result_json)} for x in rows]
@app.get("/api/reports/readings.csv")
def csv_report(db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    buf=io.StringIO(); w=csv.writer(buf); w.writerow(["reading_id","astronaut","timestamp","environment","activity","heart_rate","spo2","systolic","diastolic","sensor_quality"])
    for r in db.scalars(select(m.HealthReading).order_by(m.HealthReading.timestamp)).all(): w.writerow([r.id,r.astronaut.name,r.timestamp.isoformat(),r.environment,r.activity,r.heart_rate,r.spo2,r.systolic,r.diastolic,r.sensor_quality])
    return StreamingResponse(iter([buf.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=astra-health-readings.csv"})
@app.get("/api/dashboard")
def dashboard(db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    rr=db.scalars(select(m.HealthReading).order_by(m.HealthReading.timestamp.desc()).limit(30)).all()
    alerts_list=db.scalars(select(m.HealthAlert).where(m.HealthAlert.status=="OPEN").order_by(m.HealthAlert.created_at.desc()).limit(5)).all()
    quality={q:db.scalar(select(func.count(m.HealthReading.id)).where(m.HealthReading.sensor_quality==q)) or 0 for q in ("VALID","QUESTIONABLE","INVALID")}
    active_alert_count=db.scalar(select(func.count(m.HealthAlert.id)).where(m.HealthAlert.status=="OPEN")) or 0
    return {"astronauts":db.scalar(select(func.count(m.Astronaut.id))) or 0,"active_missions":db.scalar(select(func.count(m.Mission.id)).where(m.Mission.status=="ACTIVE")) or 0,
            "readings":db.scalar(select(func.count(m.HealthReading.id))) or 0,"approved_baselines":db.scalar(select(func.count(m.EarthBaseline.id)).where(m.EarthBaseline.status=="APPROVED")) or 0,
            "pending_reviews":db.scalar(select(func.count(m.EarthBaseline.id)).where(m.EarthBaseline.status=="PENDING")) or 0,"active_alerts":active_alert_count,
            "recent_readings":[{**dump(r),"astronaut_name":r.astronaut.name} for r in rr],"alerts":[{**dump(a),"astronaut_name":db.get(m.Astronaut,a.astronaut_id).name} for a in alerts_list],"quality":quality,
            "sync_status":"Connected to local server","generated_at":datetime.now(timezone.utc).isoformat()}

@app.get("/api/analytics")
def analytics(db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    rows=db.scalars(select(m.HealthReading).order_by(m.HealthReading.timestamp)).all()
    by_env={env:sum(1 for r in rows if r.environment==env) for env in ("EARTH","SPACE")}
    by_activity={}
    for r in rows: by_activity[r.activity]=by_activity.get(r.activity,0)+1
    return {"total":len(rows),"by_environment":by_env,"by_activity":by_activity,
            "quality":{q:sum(1 for r in rows if r.sensor_quality==q) for q in ("VALID","QUESTIONABLE","INVALID")},
            "series":[{"timestamp":r.timestamp.isoformat(),"astronaut_id":r.astronaut_id,"astronaut_name":r.astronaut.name,
                       "activity":r.activity,"environment":r.environment,"heart_rate":r.heart_rate,"spo2":r.spo2,
                       "systolic":r.systolic,"diastolic":r.diastolic,"quality":r.sensor_quality} for r in rows[-250:]]}

@app.get("/api/audit-logs")
def audit_logs(db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR"))):
    rows=db.scalars(select(m.AuditLog).order_by(m.AuditLog.created_at.desc()).limit(250)).all()
    return [{**dump(x),"user_name":db.get(m.User,x.user_id).full_name if x.user_id and db.get(m.User,x.user_id) else "System"} for x in rows]

@app.post("/api/demo/setup")
def demo_setup(db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR","RESEARCHER"))):
    mission=db.scalar(select(m.Mission).where(m.Mission.name=="Aurora Demonstration Mission"))
    if mission: return {"message":"Demo data already loaded; existing records were preserved.","mission_id":mission.id}
    mission=m.Mission(name="Aurora Demonstration Mission",status="ACTIVE",phase="ORBIT",description="Synthetic mission for classroom demonstration.",start_date="2026-11-01"); db.add(mission); db.flush()
    astronaut=m.Astronaut(name="Avery Morgan",call_sign="AURORA-01",role="Mission specialist",mission_id=mission.id); db.add(astronaut); db.flush()
    base=datetime.now(timezone.utc)-timedelta(days=8)
    for i,(act,hr) in enumerate([("RESTING",62),("RESTING",64),("RESTING",63),("RESTING",61),("RESTING",65),("WALKING",88),("WALKING",92),("WALKING",86),("WALKING",90),("WALKING",89)]):
        db.add(m.HealthReading(astronaut_id=astronaut.id,timestamp=base+timedelta(hours=i*10),heart_rate=hr,spo2=98-(i%2),systolic=112+i%4,diastolic=72+i%3,activity=act,phase="EARTH_PREPARATION",environment="EARTH",sensor_source="Demo wearable",sensor_quality="VALID"))
    db.commit()
    return {"message":"Synthetic demonstration mission and 10 Earth readings created.","mission_id":mission.id,"astronaut_id":astronaut.id}
@app.post("/api/demo/simulate-space")
def demo_space(db:Session=Depends(get_db),user:m.User=Depends(current_user)):
    astronaut=db.scalar(select(m.Astronaut).where(m.Astronaut.call_sign=="AURORA-01"))
    if not astronaut: raise HTTPException(409,"Load demo data first.")
    x=m.HealthReading(astronaut_id=astronaut.id,heart_rate=83,spo2=97,systolic=119,diastolic=76,activity="RESTING",phase="ORBIT",environment="SPACE",sensor_source="Demo wearable",sensor_quality="VALID")
    db.add(x); db.commit(); db.refresh(x)
    return {"reading":dump(x),"assessment":assess(db,x)}
@app.post("/api/demo/reset")
def demo_reset(db:Session=Depends(get_db),user:m.User=Depends(require_roles("ADMINISTRATOR"))):
    astronaut=db.scalar(select(m.Astronaut).where(m.Astronaut.call_sign=="AURORA-01"))
    mission=db.scalar(select(m.Mission).where(m.Mission.name=="Aurora Demonstration Mission"))
    if astronaut:
        reading_ids=list(db.scalars(select(m.HealthReading.id).where(m.HealthReading.astronaut_id==astronaut.id)).all())
        baseline_ids=list(db.scalars(select(m.EarthBaseline.id).where(m.EarthBaseline.astronaut_id==astronaut.id)).all())
        assessment_ids=list(db.scalars(select(m.HealthAssessment.id).where(m.HealthAssessment.reading_id.in_(reading_ids))).all()) if reading_ids else []
        if assessment_ids: db.query(m.HealthAlert).filter(m.HealthAlert.assessment_id.in_(assessment_ids)).delete(synchronize_session=False)
        if assessment_ids: db.query(m.HealthAssessment).filter(m.HealthAssessment.id.in_(assessment_ids)).delete(synchronize_session=False)
        if baseline_ids: db.query(m.BaselineApproval).filter(m.BaselineApproval.baseline_id.in_(baseline_ids)).delete(synchronize_session=False)
        if baseline_ids: db.query(m.EarthBaseline).filter(m.EarthBaseline.id.in_(baseline_ids)).delete(synchronize_session=False)
        if reading_ids:
            db.query(m.SyncRecord).filter(m.SyncRecord.reading_id.in_(reading_ids)).delete(synchronize_session=False)
            db.query(m.HealthReading).filter(m.HealthReading.id.in_(reading_ids)).delete(synchronize_session=False)
        db.delete(astronaut)
    if mission and not mission.astronauts: db.delete(mission)
    db.commit(); return {"message":"Demo records removed."}
