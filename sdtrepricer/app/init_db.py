import asyncio
from sqlalchemy import create_engine
from sdtrepricer.app.config import settings

# Import Base directly from models, not via database.py
from sdtrepricer.app.models import Base  

async def async_init_models():
    # Convert async URL to sync
    sync_url = str(settings.database_url).replace("+asyncpg", "")
    engine = create_engine(sync_url, echo=True)
    Base.metadata.create_all(engine)
    print("✅ Database tables created")

if __name__ == "__main__":
    asyncio.run(async_init_models())
