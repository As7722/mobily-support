import asyncio
from sqlalchemy import text

async def main():
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await db.execute(text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS custom_fields JSONB DEFAULT '{}'"))
        await db.commit()
        print("OK: custom_fields column added")

asyncio.run(main())
