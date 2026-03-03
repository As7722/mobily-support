"""Seed portal_fields for existing departments."""
import asyncio
import json
from sqlalchemy import select, text

DEPT_FIELDS = {
    "technical_support": [
        {"key": "ts_problem_type", "type": "select", "label_ar": "نوع المشكلة", "label_en": "Problem Type", "required": True,
         "options": [
             {"value": "fingerprint", "label_ar": "بصمة", "label_en": "Fingerprint"},
             {"value": "package_change", "label_ar": "تغيير الباقة", "label_en": "Package Change"},
             {"value": "new_activation", "label_ar": "تفعيل جديد", "label_en": "New Activation"},
             {"value": "ownership_transfer", "label_ar": "نقل ملكية", "label_en": "Ownership Transfer"},
             {"value": "other", "label_ar": "أخرى", "label_en": "Other"},
         ]},
        {"key": "ts_error_number", "type": "text", "label_ar": "رقم الخطأ", "label_en": "Error Number",
         "placeholder_ar": "أدخل رقم الخطأ", "placeholder_en": "Enter error number",
         "required": True, "half_width": True, "dir": "ltr"},
    ],
    "user_management": [
        {"key": "um_problem_type", "type": "select", "label_ar": "نوع المشكلة", "label_en": "Problem Type", "required": True,
         "options": [
             {"value": "fingerprint_error", "label_ar": "خطأ بصمة", "label_en": "Fingerprint Error"},
             {"value": "reader", "label_ar": "قارئ البصمة", "label_en": "Fingerprint Reader"},
             {"value": "system_access", "label_ar": "مشكلة دخول لنظام", "label_en": "System Access Issue"},
             {"value": "user_auth", "label_ar": "مشكلة توثيق اليوزر", "label_en": "User Auth Issue"},
             {"value": "other", "label_ar": "أخرى", "label_en": "Other"},
         ]},
        {"key": "um_error_number", "type": "text", "label_ar": "رقم الخطأ", "label_en": "Error Number",
         "placeholder_ar": "أدخل رقم الخطأ", "required": True, "half_width": True, "dir": "ltr"},
        {"key": "um_reader_number", "type": "text", "label_ar": "رقم القارئ", "label_en": "Reader Number",
         "placeholder_ar": "أدخل رقم القارئ", "required": True, "half_width": True, "dir": "ltr"},
    ],
    "device_activation": [
        {"key": "device_problem_type", "type": "select", "label_ar": "نوع المشكلة", "label_en": "Problem Type", "required": True,
         "options": [
             {"value": "mobile", "label_ar": "تفعيل جوال بالخطأ", "label_en": "Wrong Mobile Activation"},
             {"value": "router", "label_ar": "تفعيل راوتر بالخطأ", "label_en": "Wrong Router Activation"},
         ]},
        {"key": "device_number", "type": "text", "label_ar": "رقم الجهاز", "label_en": "Device Number",
         "placeholder_ar": "أدخل رقم الجهاز", "required": True, "half_width": True, "dir": "ltr"},
        {"key": "activation_type", "type": "select", "label_ar": "نوع التفعيل", "label_en": "Activation Type", "required": True,
         "options": [
             {"value": "display", "label_ar": "بعرض", "label_en": "Display"},
             {"value": "cash", "label_ar": "كاش", "label_en": "Cash"},
         ]},
    ],
    "absher": [
        {"key": "absher_problem_type", "type": "select", "label_ar": "نوع المشكلة", "label_en": "Problem Type", "required": True,
         "options": [
             {"value": "absher_app", "label_ar": "مشكلة تطبيق أبشر", "label_en": "Absher App Issue"},
             {"value": "fingerprint_reader", "label_ar": "مشكلة قارئ البصمة", "label_en": "Fingerprint Reader Issue"},
             {"value": "tablet_issue", "label_ar": "مشكلة التابلت", "label_en": "Tablet Issue"},
             {"value": "charger_issue", "label_ar": "مشكلة شاحن التابلت", "label_en": "Tablet Charger Issue"},
         ]},
        {"key": "absher_tablet_number", "type": "text", "label_ar": "رقم التابلت", "label_en": "Tablet Number",
         "placeholder_ar": "أدخل رقم التابلت", "required": True, "half_width": True, "dir": "ltr"},
    ],
}

async def main():
    from app.core.database import AsyncSessionLocal
    from app.models.department import Department

    async with AsyncSessionLocal() as db:
        for code, fields in DEPT_FIELDS.items():
            result = await db.execute(select(Department).where(Department.code == code))
            dept = result.scalar_one_or_none()
            if dept:
                dept.portal_fields = fields
                print(f"  UPDATED: {code} ({len(fields)} fields)")
            else:
                print(f"  SKIP: {code} not found")
        await db.commit()
        print("OK: portal_fields seeded")

asyncio.run(main())
