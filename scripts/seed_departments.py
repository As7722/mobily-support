"""Seed the 4 core departments used by the portal ticket form."""
import asyncio
import uuid

from sqlalchemy import select, text


DEPARTMENTS = [
    {"code": "technical_support",  "name_ar": "الدعم التقني",            "name_en": "Technical Support"},
    {"code": "user_management",    "name_ar": "إدارة اليوزرات",           "name_en": "User Management"},
    {"code": "device_activation",  "name_ar": "التفعيل الخاطئ للأجهزة", "name_en": "Device Activation Error"},
    {"code": "absher",             "name_ar": "أبشر",                    "name_en": "Absher"},
]


async def main() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.department import Department

    async with AsyncSessionLocal() as db:
        for dept_data in DEPARTMENTS:
            existing = await db.execute(
                select(Department).where(Department.code == dept_data["code"], Department.deleted_at.is_(None))
            )
            if existing.scalar_one_or_none():
                print(f"  EXISTS: {dept_data['code']}")
                continue

            db.add(Department(
                id=uuid.uuid4(),
                code=dept_data["code"],
                name_ar=dept_data["name_ar"],
                name_en=dept_data["name_en"],
                is_active=True,
            ))
            print(f"  CREATED: {dept_data['code']}")

        await db.commit()
        print("OK: Departments seeded")


asyncio.run(main())
