import asyncio
from sqlalchemy import text

async def main():
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await db.execute(text("""CREATE TABLE IF NOT EXISTS user_departments (
            user_id UUID REFERENCES users(id),
            department_id UUID REFERENCES departments(id),
            created_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (user_id, department_id)
        )"""))
        await db.execute(text("ALTER TABLE departments ADD COLUMN IF NOT EXISTS portal_fields JSONB DEFAULT '[]'"))
        await db.commit()
        print("OK: migration 011 applied")

asyncio.run(main())
