import asyncio
from sqlalchemy import text

async def main():
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        r = await db.execute(text("SELECT ticket_number, current_queue, sub_queue_dept_id, custom_fields FROM tickets WHERE ticket_number='CSTS-018'"))
        row = r.first()
        if row:
            print(f"ticket: {row[0]} | queue: {row[1]} | dept: {row[2]}")
            print(f"custom: {row[3]}")

asyncio.run(main())
