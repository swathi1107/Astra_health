import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/astra_health.db")
DEVIATION_THRESHOLD = float(os.getenv("DEVIATION_THRESHOLD", "2.0"))
