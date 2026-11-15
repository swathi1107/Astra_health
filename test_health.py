import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.database import Base, get_db
from backend.main import app

engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
TestingSession=sessionmaker(bind=engine,autoflush=False,autocommit=False)
Base.metadata.create_all(engine)
def override_db():
    db=TestingSession()
    try: yield db
    finally: db.close()
app.dependency_overrides[get_db]=override_db

@pytest.fixture
def anyio_backend(): return 'asyncio'

@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    yield

@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://astra.test') as c:
        response=await c.post('/api/auth/bootstrap',json={'email':'admin@example.test','full_name':'Demo Administrator','password':'SafePassphrase-1234'})
        assert response.status_code==200
        yield c

def demo_setup(): return {'email':'admin@example.test','full_name':'Demo Administrator','password':'SafePassphrase-1234'}

@pytest.mark.anyio
async def test_health_and_frontend(client):
    assert (await client.get('/api/health')).json()['status']=='ok'
    assert (await client.get('/')).status_code==200
    assert (await client.get('/dashboard.html')).status_code==200
    assert (await client.get('/login.html')).status_code==200
    assert (await client.get('/static/vendor/chart.umd.min.js')).status_code==200

@pytest.mark.anyio
async def test_authenticated_roles_and_secure_session(client):
    assert (await client.get('/api/auth/setup-status')).json()['needs_admin'] is False
    assert (await client.get('/api/auth/me')).json()['role']=='ADMINISTRATOR'
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://astra.test') as anonymous:
        assert (await anonymous.get('/api/dashboard')).status_code==401
    created=await client.post('/api/users',json={'email':'reviewer@example.test','full_name':'Review Officer','password':'ReviewPassphrase-1','role':'MEDICAL_OFFICER'})
    assert created.status_code==200
    await client.post('/api/auth/logout')
    login=await client.post('/api/auth/login',json={'email':'reviewer@example.test','password':'ReviewPassphrase-1'})
    assert login.status_code==200 and login.json()['user']['role']=='MEDICAL_OFFICER'
    changed=await client.post('/api/auth/password',json={'current_password':'ReviewPassphrase-1','new_password':'ReviewPassphrase-2'})
    assert changed.status_code==200
    await client.post('/api/auth/logout')
    assert (await client.post('/api/auth/login',json={'email':'reviewer@example.test','password':'ReviewPassphrase-1'})).status_code==401
    assert (await client.post('/api/auth/login',json={'email':'reviewer@example.test','password':'ReviewPassphrase-2'})).status_code==200
    await client.post('/api/auth/logout')
    await client.post('/api/auth/login',json=demo_setup())
    await client.post('/api/users',json={'email':'crew@example.test','full_name':'Crew Member','password':'CrewPassphrase-1234','role':'ASTRONAUT'})
    await client.post('/api/auth/logout')
    assert (await client.post('/api/auth/login',json={'email':'crew@example.test','password':'CrewPassphrase-1234'})).status_code==200
    assert (await client.post('/api/missions',json={'name':'Restricted mission'})).status_code==403
    await client.post('/api/auth/logout')
    await client.post('/api/auth/login',json=demo_setup())
    crew=(await client.get('/api/users')).json()
    crew=next(x for x in crew if x['email']=='crew@example.test')
    assert (await client.put(f"/api/users/{crew['id']}",json={'active':False})).json()['active'] is False
    await client.post('/api/auth/logout')
    assert (await client.post('/api/auth/login',json={'email':'crew@example.test','password':'CrewPassphrase-1234'})).status_code==401

@pytest.mark.anyio
async def test_baseline_requires_five_samples_then_review_and_assessment(client):
    aid=(await client.post('/api/demo/setup')).json()['astronaut_id']
    response=await client.post(f'/api/baselines/generate?astronaut_id={aid}&activity=RESTING')
    assert response.status_code==200
    baseline=(await client.get('/api/baselines')).json()[0]
    assert baseline['sample_count']==5 and baseline['status']=='PENDING'
    notifications=(await client.get('/api/notifications')).json()
    assert any(x['unread'] for x in notifications)
    reviewed=await client.post(f"/api/baselines/{baseline['id']}/review",json={'decision':'APPROVED','comments':'Checked in test.'})
    assert reviewed.status_code==200
    reading=await client.post('/api/readings',json={'astronaut_id':aid,'heart_rate':95,'spo2':97,'activity':'RESTING','phase':'ORBIT','environment':'SPACE','sensor_quality':'VALID'})
    result=reading.json()['assessment']
    assert result['comparison_available'] is True
    assert result['severity']=='REVIEW_REQUIRED'
    assert len((await client.get('/api/alerts')).json())==1
    assert len((await client.get('/api/notifications')).json())>=2

@pytest.mark.anyio
async def test_invalid_samples_excluded_and_missing_baseline_safe(client):
    aid=(await client.post('/api/demo/setup')).json()['astronaut_id']
    await client.post('/api/readings',json={'astronaut_id':aid,'heart_rate':200,'activity':'RESTING','environment':'EARTH','sensor_quality':'INVALID'})
    baseline=(await client.post(f'/api/baselines/generate?astronaut_id={aid}&activity=RESTING')).json()
    assert baseline['sample_count']==5
    reading=await client.post('/api/readings',json={'astronaut_id':aid,'heart_rate':200,'activity':'EXERCISE','phase':'ORBIT','environment':'SPACE','sensor_quality':'VALID'})
    result=reading.json()['assessment']
    assert result['comparison_available'] is False
    assert 'not approved' in result['message'].lower()

@pytest.mark.anyio
async def test_fewer_than_five_valid_earth_samples_cannot_make_baseline(client):
    aid=(await client.post('/api/demo/setup')).json()['astronaut_id']
    response=await client.post(f'/api/baselines/generate?astronaut_id={aid}&activity=SLEEPING')
    assert response.status_code==422
    assert 'At least 5 valid Earth readings' in response.json()['detail']

@pytest.mark.anyio
async def test_csv_idempotency_and_demo_reset(client):
    demo=(await client.post('/api/demo/setup')).json()
    again=(await client.post('/api/demo/setup')).json()
    assert again['mission_id']==demo['mission_id']
    assert len((await client.get('/api/readings')).json())==10
    baseline=(await client.post(f"/api/baselines/generate?astronaut_id={demo['astronaut_id']}&activity=RESTING")).json()
    await client.post(f"/api/baselines/{baseline['id']}/review",json={'decision':'APPROVED'})
    await client.post('/api/demo/simulate-space')
    assert 'text/csv' in (await client.get('/api/reports/readings.csv')).headers['content-type']
    assert (await client.post('/api/demo/reset')).status_code==200
    assert (await client.get('/api/astronauts')).json()==[]
    assert (await client.get('/api/baselines')).json()==[]
    assert (await client.get('/api/alerts')).json()==[]

@pytest.mark.anyio
async def test_reading_legacy_field_names_and_idempotency(client):
    aid=(await client.post('/api/demo/setup')).json()['astronaut_id']
    payload={'astronaut_id':aid,'heart_rate':67,'systolic_bp':118,'diastolic_bp':75,'mission_phase':'EARTH_PREPARATION','quality_status':'VALID','recorded_at':'2026-10-01T10:00:00Z','client_request_id':'test-request-001'}
    first=await client.post('/api/readings',json=payload)
    second=await client.post('/api/readings',json=payload)
    assert first.status_code==200 and second.json()['duplicate'] is True
    assert second.json()['reading']['systolic_bp']==118
    assert len((await client.get('/api/readings')).json())==11
