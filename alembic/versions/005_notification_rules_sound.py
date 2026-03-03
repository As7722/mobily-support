"""Add sound_enabled + sound_file to notification_rules; seed default rules.

Revision ID: 005
Revises: 004
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Add new columns
    conn.execute(sa.text("""
        ALTER TABLE notification_rules
        ADD COLUMN IF NOT EXISTS sound_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        ADD COLUMN IF NOT EXISTS sound_file    VARCHAR(100) DEFAULT 'default',
        ADD COLUMN IF NOT EXISTS name_ar       VARCHAR(120),
        ADD COLUMN IF NOT EXISTS name_en       VARCHAR(120),
        ADD COLUMN IF NOT EXISTS description_ar TEXT,
        ADD COLUMN IF NOT EXISTS description_en TEXT
    """))

    # Seed default notification rules
    rules = [
        ("ticket_assigned",       ["employee", "supervisor", "manager"],   ["in_app"], True,  "default", "تذكرة مُسندة",       "Ticket Assigned"),
        ("ticket_escalated",      ["supervisor", "manager"],               ["in_app"], True,  "alert",   "تصعيد تذكرة",        "Ticket Escalated"),
        ("ticket_replied",        ["employee", "supervisor"],              ["in_app"], True,  "chime",   "رد جديد",            "New Reply"),
        ("ticket_status_changed", ["employee", "supervisor", "manager"],   ["in_app"], True,  "default", "تغيير الحالة",       "Status Changed"),
        ("ticket_created",        ["supervisor", "manager"],               ["in_app"], True,  "chime",   "تذكرة جديدة",        "New Ticket"),
        ("sla_breach",            ["employee", "supervisor", "manager"],   ["in_app"], True,  "urgent",  "خرق SLA",            "SLA Breach"),
        ("sla_warning",           ["employee", "supervisor"],              ["in_app"], True,  "warning", "تحذير SLA",          "SLA Warning"),
        ("ticket_resolved",       ["supervisor", "manager"],               ["in_app"], False, "success", "تذكرة محلولة",       "Ticket Resolved"),
        ("ticket_closed",         ["supervisor", "manager"],               ["in_app"], False, "default", "تذكرة مغلقة",        "Ticket Closed"),
        ("ticket_transferred",    ["employee"],                            ["in_app"], True,  "chime",   "تحويل تذكرة",        "Ticket Transferred"),
        ("ticket_merged",         ["employee", "supervisor"],              ["in_app"], False, "default", "دمج تذاكر",          "Tickets Merged"),
        ("ticket_split",          ["employee", "supervisor"],              ["in_app"], False, "default", "تقسيم تذكرة",        "Ticket Split"),
        ("mention",               ["employee", "supervisor", "manager"],   ["in_app"], True,  "mention", "ذكر",                "Mention"),
        ("system",                ["employee", "supervisor", "manager"],   ["in_app"], False, "default", "إشعار النظام",       "System"),
    ]

    for (event, roles, channels, sound, sound_file, name_ar, name_en) in rules:
        roles_pg = "ARRAY[" + ",".join(f"'{r}'" for r in roles) + "]"
        chan_pg  = "ARRAY[" + ",".join(f"'{c}'" for c in channels) + "]"
        sound_val = "TRUE" if sound else "FALSE"
        conn.execute(sa.text(f"""
            INSERT INTO notification_rules
                (id, event_type, target_roles, channels, is_active,
                 sound_enabled, sound_file, name_ar, name_en)
            VALUES (gen_random_uuid(), '{event}', {roles_pg}, {chan_pg}, TRUE,
                    {sound_val}, '{sound_file}', '{name_ar}', '{name_en}')
            ON CONFLICT DO NOTHING
        """))


def downgrade() -> None:
    pass
