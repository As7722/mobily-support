"""
Seed script — Mobily Tech Support System
Usage:
    python scripts/seed.py

Creates:
  - 4 users  (admin, supervisor, manager, employee)
  - 5 branches
  - 4 categories (Network, POS, Devices, Software) with sub-categories
  - 4 SLA policies (critical/high/medium/low)
  - Full role_permissions matrix for all roles
  - Initial branding config
  - Default feature flags
  - Sample canned responses
  - Sample gamification badges
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running from project root: python scripts/seed.py
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password

# ── PERMISSION MATRIX from SPEC.md Section 4.2 ───────────────────────────────
PERMISSIONS: dict[str, list[str]] = {
    "employee": [
        "tickets.view_own", "tickets.claim_main_queue", "tickets.resolve",
        "tickets.close", "tickets.transfer_to_supervisor_queue", "tickets.escalate",
        "tickets.add_watcher", "reports.personal_dashboard", "reports.leaderboard_partial",
        "schedule.view_own", "schedule.request_swap", "schedule.request_leave",
        "kb.read", "gamification.view_own_badges", "ui.dark_light_mode",
        "ui.language_toggle", "config.canned_responses",
    ],
    "supervisor": [
        # Inherits employee + extras
        "tickets.view_own", "tickets.view_team", "tickets.view_all",
        "tickets.claim_main_queue", "tickets.claim_supervisor_queue",
        "tickets.resolve", "tickets.close", "tickets.reopen", "tickets.reassign",
        "tickets.transfer_to_supervisor_queue", "tickets.transfer_to_manager_queue",
        "tickets.return_to_agent", "tickets.return_to_main_queue",
        "tickets.escalate", "tickets.merge", "tickets.split",
        "tickets.add_watcher", "tickets.lock_unlock",
        "users.create", "users.edit", "users.disable", "users.reset_password",
        "users.import_export_excel", "users.set_backup_agent",
        "branches.create_edit", "branches.disable", "branches.import_export_excel",
        "branches.internal_notes", "branches.broadcast_email", "branches.manage_employees",
        "reports.personal_dashboard", "reports.leaderboard_partial", "reports.leaderboard_full",
        "reports.team_performance", "reports.export_team_csv",
        "schedule.view_own", "schedule.view_team", "schedule.edit",
        "schedule.request_swap", "schedule.approve_swap",
        "schedule.request_leave", "schedule.approve_leave",
        "kb.read", "kb.create_edit", "kb.delete", "kb.view_stats",
        "gamification.view_own_badges", "gamification.announce_employee_month",
        "gamification.grant_badge_manually",
        "config.canned_responses", "ui.dark_light_mode", "ui.language_toggle",
    ],
    "manager": [
        # Inherits supervisor + extras
        "tickets.view_own", "tickets.view_team", "tickets.view_all",
        "tickets.claim_main_queue", "tickets.claim_supervisor_queue",
        "tickets.claim_manager_queue",
        "tickets.resolve", "tickets.close", "tickets.reopen", "tickets.reassign",
        "tickets.transfer_to_supervisor_queue", "tickets.transfer_to_manager_queue",
        "tickets.return_to_agent", "tickets.return_to_main_queue",
        "tickets.escalate", "tickets.merge", "tickets.split",
        "tickets.add_watcher", "tickets.lock_unlock",
        "users.create", "users.edit", "users.disable", "users.reset_password",
        "users.import_export_excel", "users.set_backup_agent",
        "users.view_active_sessions", "users.force_logout_single",
        "branches.create_edit", "branches.disable", "branches.import_export_excel",
        "branches.internal_notes", "branches.broadcast_email", "branches.manage_employees",
        "reports.personal_dashboard", "reports.leaderboard_partial", "reports.leaderboard_full",
        "reports.team_performance", "reports.executive_kpi", "reports.advanced_builder",
        "reports.scheduled_reports", "reports.export_team_csv", "reports.export_full",
        "reports.audit_log_read",
        "schedule.view_own", "schedule.view_team", "schedule.edit",
        "schedule.request_swap", "schedule.approve_swap",
        "schedule.request_leave", "schedule.approve_leave",
        "kb.read", "kb.create_edit", "kb.delete", "kb.view_stats",
        "gamification.view_own_badges", "gamification.announce_employee_month",
        "gamification.grant_badge_manually", "gamification.edit_criteria",
        "config.sla_rules", "config.automation_rules", "config.form_builder",
        "config.categories_tags", "config.canned_responses",
        "config.system_alerts", "config.gamification",
        "config.notification_rules",
        "ui.dark_light_mode", "ui.language_toggle",
    ],
}

# Admin has all permissions (checked at runtime) — no DB rows needed except explicit overrides


async def seed(session: AsyncSession) -> None:
    from sqlalchemy import text

    print("🌱  Starting seed...")

    # ── Departments ──────────────────────────────────────────────────────────
    print("  → Creating departments...")
    await session.execute(text("""
        INSERT INTO departments (name_ar, name_en, code) VALUES
          ('دعم الشبكة',      'Network Support',  'NET'),
          ('دعم نقاط البيع',  'POS Support',      'POS'),
          ('دعم الأجهزة',     'Device Support',   'DEV'),
          ('دعم البرمجيات',   'Software Support', 'SW')
        ON CONFLICT (code) DO NOTHING
    """))

    # ── SLA Policies ─────────────────────────────────────────────────────────
    print("  → Creating SLA policies...")
    await session.execute(text("""
        INSERT INTO sla_policies (name_ar, name_en, priority, clock_minutes) VALUES
          ('حرجة - 30 دقيقة',  'Critical - 30 minutes', 'critical', 30),
          ('عالية - 2 ساعة',   'High - 2 hours',        'high',     120),
          ('متوسطة - 8 ساعات', 'Medium - 8 hours',      'medium',   480),
          ('منخفضة - 24 ساعة', 'Low - 24 hours',        'low',      1440)
        ON CONFLICT DO NOTHING
    """))

    # ── Users ────────────────────────────────────────────────────────────────
    print("  → Creating users...")
    admin_hash     = hash_password("Admin@1234")
    sup_hash       = hash_password("Sup@1234")
    mgr_hash       = hash_password("Mgr@1234")
    emp_hash       = hash_password("Emp@1234")

    await session.execute(text("""
        INSERT INTO users (username, email, full_name_ar, full_name_en,
                           employee_id, role, password_hash, preferred_language)
        VALUES
          ('admin',      'admin@mobily.com.sa',      'مدير النظام',    'System Admin',   'EMP-0001', 'admin',      :admin_hash, 'ar'),
          ('supervisor', 'supervisor@mobily.com.sa', 'محمد المشرف',    'Mohamed Sup',    'EMP-0002', 'supervisor', :sup_hash,   'ar'),
          ('manager',    'manager@mobily.com.sa',    'خالد المدير',    'Khaled Manager', 'EMP-0003', 'manager',    :mgr_hash,   'ar'),
          ('employee',   'employee@mobily.com.sa',   'أحمد الأحمدي',  'Ahmed Al-Ahmadi','EMP-0004', 'employee',   :emp_hash,   'ar')
        ON CONFLICT (username) DO NOTHING
    """), {
        "admin_hash": admin_hash,
        "sup_hash": sup_hash,
        "mgr_hash": mgr_hash,
        "emp_hash": emp_hash,
    })

    # ── Branches ─────────────────────────────────────────────────────────────
    print("  → Creating branches...")
    await session.execute(text("""
        INSERT INTO branches (name_ar, name_en, code, city_ar, city_en, region_ar, region_en) VALUES
          ('فرع الرياض المركزي', 'Riyadh Main Branch',  'RYD-01', 'الرياض',  'Riyadh',  'منطقة الرياض',   'Riyadh Region'),
          ('فرع جدة المركزي',    'Jeddah Main Branch',  'JED-01', 'جدة',     'Jeddah',  'منطقة مكة',      'Makkah Region'),
          ('فرع الدمام',         'Dammam Branch',       'DAM-01', 'الدمام',  'Dammam',  'المنطقة الشرقية','Eastern Region'),
          ('فرع مكة المكرمة',    'Makkah Branch',       'MKH-01', 'مكة المكرمة','Makkah','منطقة مكة',     'Makkah Region'),
          ('فرع المدينة المنورة', 'Madinah Branch',     'MDN-01', 'المدينة المنورة','Madinah','منطقة المدينة','Madinah Region')
        ON CONFLICT (code) DO NOTHING
    """))

    # ── Branch Employees ───────────────────────────────────────────────────────
    print("  → Creating branch employees...")
    await session.execute(text("""
        INSERT INTO branch_employees (id, branch_id, full_name_ar, full_name_en, employee_id, phone, email, position_ar, position_en, preferred_language, is_active)
        SELECT
          gen_random_uuid(),
          b.id,
          e.name_ar,
          e.name_en,
          e.emp_id,
          e.phone,
          e.email,
          e.pos_ar,
          e.pos_en,
          'ar',
          true
        FROM (VALUES
          ('RYD-01', 'عبدالله أحمد الشهري',    'Abdullah Ahmed',      'EMP-1001', '0599588828', 'abdullah@mobily.com.sa',  'مسؤول مبيعات',   'Sales Officer'),
          ('RYD-01', 'فهد سعد القحطاني',       'Fahd Saad',           'EMP-1002', '0551234567', 'fahd.s@mobily.com.sa',   'مسؤول خدمة عملاء','Customer Service'),
          ('RYD-01', 'نورة خالد العتيبي',       'Noura Khalid',        'EMP-1003', '0561112233', 'noura.k@mobily.com.sa',  'مديرة فرع',      'Branch Manager'),
          ('JED-01', 'سارة محمد الحربي',        'Sara Mohammed',       'EMP-2001', '0509876543', 'sara.m@mobily.com.sa',   'مسؤولة مبيعات',  'Sales Officer'),
          ('JED-01', 'أحمد علي الزهراني',       'Ahmed Ali',           'EMP-2002', '0543216789', 'ahmed.z@mobily.com.sa',  'فني دعم تقني',   'Tech Support'),
          ('JED-01', 'ريم عبدالرحمن',          'Reem Abdulrahman',    'EMP-2003', '0578901234', 'reem.a@mobily.com.sa',   'مسؤولة خدمة عملاء','Customer Service'),
          ('DAM-01', 'خالد العمري',            'Khalid Al-Omari',     'EMP-3001', '0532145678', 'khalid.o@mobily.com.sa', 'مسؤول مبيعات',   'Sales Officer'),
          ('DAM-01', 'محمد الدوسري',           'Mohammed Al-Dosari',  'EMP-3002', '0567891234', 'mohammed.d@mobily.com.sa','فني صيانة',     'Maintenance Tech'),
          ('MKH-01', 'عمر حسين الغامدي',       'Omar Hussein',        'EMP-4001', '0512349876', 'omar.g@mobily.com.sa',   'مسؤول مبيعات',   'Sales Officer'),
          ('MKH-01', 'ليلى ناصر',              'Layla Nasser',        'EMP-4002', '0598765432', 'layla.n@mobily.com.sa',  'مسؤولة خدمة عملاء','Customer Service'),
          ('MDN-01', 'سلطان العنزي',           'Sultan Al-Anazi',     'EMP-5001', '0545671234', 'sultan.a@mobily.com.sa', 'مدير فرع',       'Branch Manager'),
          ('MDN-01', 'هند الشمري',             'Hind Al-Shammari',    'EMP-5002', '0523456789', 'hind.s@mobily.com.sa',   'مسؤولة مبيعات',  'Sales Officer')
        ) AS e(branch_code, name_ar, name_en, emp_id, phone, email, pos_ar, pos_en)
        JOIN branches b ON b.code = e.branch_code AND b.deleted_at IS NULL
        WHERE NOT EXISTS (SELECT 1 FROM branch_employees be WHERE be.employee_id = e.emp_id AND be.deleted_at IS NULL)
    """))

    # ── Categories ────────────────────────────────────────────────────────────
    print("  → Creating categories...")
    await session.execute(text("""
        INSERT INTO categories (name_ar, name_en)
        VALUES
          ('الشبكة',         'Network'),
          ('نقاط البيع',     'POS System'),
          ('الأجهزة',        'Devices'),
          ('البرمجيات',      'Software')
        ON CONFLICT DO NOTHING
    """))

    # Sub-categories (get parent IDs first)
    result = await session.execute(text(
        "SELECT id, name_en FROM categories WHERE name_en IN ('Network','POS System','Devices','Software')"
    ))
    cat_map = {row[1]: row[0] for row in result.fetchall()}

    if cat_map:
        subcats = [
            ("انقطاع الإنترنت", "Internet Outage",      cat_map.get("Network")),
            ("بطء الشبكة",      "Network Slow",          cat_map.get("Network")),
            ("توقف نقطة البيع", "POS Not Working",       cat_map.get("POS System")),
            ("طباعة الإيصالات", "Receipt Printer Issue", cat_map.get("POS System")),
            ("جهاز لا يعمل",    "Device Not Powering",   cat_map.get("Devices")),
            ("مشكلة شاشة",      "Screen Issue",          cat_map.get("Devices")),
            ("خطأ في النظام",   "System Error",          cat_map.get("Software")),
            ("مشكلة تسجيل دخول","Login Problem",         cat_map.get("Software")),
        ]
        for name_ar, name_en, parent_id in subcats:
            if parent_id:
                await session.execute(text("""
                    INSERT INTO categories (name_ar, name_en, parent_id)
                    VALUES (:ar, :en, :pid)
                    ON CONFLICT DO NOTHING
                """), {"ar": name_ar, "en": name_en, "pid": str(parent_id)})

    # ── Role Permissions ──────────────────────────────────────────────────────
    print("  → Seeding role permissions...")
    for role, perms in PERMISSIONS.items():
        for perm_key in perms:
            await session.execute(text("""
                INSERT INTO role_permissions (role, permission_key, is_granted)
                VALUES (:role, :key, TRUE)
                ON CONFLICT (role, permission_key) DO NOTHING
            """), {"role": role, "key": perm_key})

    # ── Canned Responses ──────────────────────────────────────────────────────
    print("  → Creating canned responses...")
    await session.execute(text("""
        INSERT INTO canned_responses (shortcut, name_ar, name_en, content_ar, content_en)
        VALUES
          ('/greeting',
           'تحية',
           'Greeting',
           'مرحباً، شكراً لتواصلك مع الدعم التقني لموبايلي. يسعدني مساعدتك.',
           'Hello, thank you for contacting Mobily Technical Support. I am happy to assist you.'),
          ('/checking',
           'قيد المراجعة',
           'Under Review',
           'نقوم حالياً بمراجعة طلبك وسنرد عليك في أقرب وقت ممكن.',
           'We are currently reviewing your request and will get back to you as soon as possible.'),
          ('/resolved',
           'تم الحل',
           'Resolved',
           'تم حل المشكلة بنجاح. يرجى إعلامنا إذا كنت بحاجة إلى أي مساعدة إضافية.',
           'The issue has been successfully resolved. Please let us know if you need any further assistance.'),
          ('/escalating',
           'تصعيد',
           'Escalating',
           'يتم تصعيد هذه المشكلة إلى الفريق المختص وسيتواصل معك قريباً.',
           'This issue is being escalated to the specialized team and they will contact you shortly.')
        ON CONFLICT (shortcut) DO NOTHING
    """))

    # ── Gamification Badges ───────────────────────────────────────────────────
    print("  → Creating gamification badges...")
    await session.execute(text("""
        INSERT INTO gamification_badges (name_ar, name_en, description_ar, description_en, icon_emoji, criteria)
        VALUES
          ('الحل السريع',    'Speed Resolver',
           'يحل أكثر من 10 تذاكر في يوم واحد',
           'Resolves more than 10 tickets in one day',
           '⚡',
           '{"metric": "tickets_resolved_today", "operator": ">=", "value": 10}'),
          ('بطل الجودة',    'Quality Champion',
           'يحصل على تقييم 5 نجوم لمدة 5 تذاكر متتالية',
           'Receives 5-star rating for 5 consecutive tickets',
           '⭐',
           '{"metric": "consecutive_5star_csat", "operator": ">=", "value": 5}'),
          ('صياد الحرجة',   'Critical Hunter',
           'يحل 5 تذاكر حرجة في الوقت المحدد',
           'Resolves 5 critical tickets within SLA',
           '🎯',
           '{"metric": "critical_tickets_within_sla", "operator": ">=", "value": 5}'),
          ('موظف الشهر',    'Employee of the Month',
           'أفضل موظف لهذا الشهر',
           'Best employee of the month',
           '🏆',
           '{"metric": "employee_of_month", "operator": "eq", "value": true}')
        ON CONFLICT DO NOTHING
    """))

    # ── Default Feature Flags ─────────────────────────────────────────────────
    print("  → Creating feature flags...")
    flags = [
        ("csat_enabled",        "تفعيل استبيان رضا العملاء",   "Enable CSAT surveys",           True),
        ("whatsapp_enabled",    "تفعيل واتساب",                 "Enable WhatsApp integration",   False),
        ("sms_enabled",         "تفعيل الرسائل القصيرة",        "Enable SMS notifications",      False),
        ("email_ingestion",     "تفعيل استيراد البريد الإلكتروني","Enable IMAP email ingestion",  False),
        ("2fa_required_admin",  "إلزامية المصادقة الثنائية للمدير","Require 2FA for admin",       True),
        ("gamification_enabled","تفعيل نظام التحفيز",           "Enable gamification system",   True),
        ("dark_mode_enabled",   "تفعيل الوضع المظلم",           "Enable dark mode",             True),
        ("public_status_page",  "صفحة الحالة العامة",           "Enable public status page",    True),
    ]
    for key, name_ar, name_en, enabled in flags:
        await session.execute(text("""
            INSERT INTO feature_flags (key, name_ar, name_en, is_enabled)
            VALUES (:key, :name_ar, :name_en, :enabled)
            ON CONFLICT (key) DO NOTHING
        """), {"key": key, "name_ar": name_ar, "name_en": name_en, "enabled": enabled})

    # ── System Statuses (for /status page) ───────────────────────────────────
    print("  → Creating system statuses...")
    await session.execute(text("""
        INSERT INTO system_statuses (system_name_ar, system_name_en, sort_order) VALUES
          ('نظام نقاط البيع',       'POS System',           1),
          ('نظام إدارة العملاء CRM', 'CRM System',           2),
          ('نظام الشحن',            'Recharge System',      3),
          ('الشبكة الداخلية',        'Internal Network',     4),
          ('نظام الفوترة',           'Billing System',       5)
        ON CONFLICT DO NOTHING
    """))

    # ── Commit ────────────────────────────────────────────────────────────────
    await session.commit()
    print("\n✅  Seed complete!")
    print("\nTest credentials:")
    print("  admin      / Admin@1234  (role: admin)")
    print("  supervisor / Sup@1234   (role: supervisor)")
    print("  manager    / Mgr@1234   (role: manager)")
    print("  employee   / Emp@1234   (role: employee)")
    print("\nRun: POST http://localhost:8000/api/auth/login")


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
