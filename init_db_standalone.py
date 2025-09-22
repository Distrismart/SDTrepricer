# /opt/SDTrepricer/init_db_standalone.py

import os
import sys
import importlib.util
from sqlalchemy import create_engine

# Force-load models.py as proper package module
module_name = "sdtrepricer.app.models"
spec = importlib.util.spec_from_file_location(
    module_name, "/app/sdtrepricer/app/models.py"
)
models = importlib.util.module_from_spec(spec)
sys.modules[module_name] = models
spec.loader.exec_module(models)

Base = models.Base

# Get DB URL
database_url = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://repricer:repricer@db:5432/repricer"
)

# Convert async driver to sync
sync_url = database_url.replace("+asyncpg", "")
engine = create_engine(sync_url, echo=True)

print("👉 Creating tables...")
Base.metadata.create_all(bind=engine)
print("✅ Done, tables created.")
