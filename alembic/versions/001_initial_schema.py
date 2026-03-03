"""Initial schema — all 50 tables

Revision ID: 001
Revises:
Create Date: 2026-02-27
"""
from __future__ import annotations

from alembic import op

revision: str = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "unaccent"')

    # ── 1. departments ────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS departments (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name_ar     VARCHAR(100) NOT NULL,
        name_en     VARCHAR(100) NOT NULL,
        code        VARCHAR(20)  UNIQUE NOT NULL,
        is_active   BOOLEAN DEFAULT TRUE,
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        updated_at  TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 2. sla_policies ───────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS sla_policies (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name_ar             VARCHAR(100) NOT NULL,
        name_en             VARCHAR(100) NOT NULL,
        priority            VARCHAR(20)  NOT NULL,
        clock_minutes       INTEGER NOT NULL,
        business_hours_only BOOLEAN DEFAULT TRUE,
        is_active           BOOLEAN DEFAULT TRUE,
        created_at          TIMESTAMPTZ DEFAULT NOW(),
        updated_at          TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 3. users ──────────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username            VARCHAR(50)  UNIQUE NOT NULL,
        email               VARCHAR(255) UNIQUE,
        phone               VARCHAR(20),
        full_name_ar        VARCHAR(150) NOT NULL,
        full_name_en        VARCHAR(150),
        employee_id         VARCHAR(50)  UNIQUE,
        role                VARCHAR(20)  NOT NULL
                            CHECK (role IN ('employee','supervisor','manager','admin')),
        department_id       UUID REFERENCES departments(id),
        preferred_language  VARCHAR(5)   DEFAULT 'ar'
                            CHECK (preferred_language IN ('ar','en')),
        password_hash       VARCHAR(255) NOT NULL,
        totp_secret         VARCHAR(100),
        totp_enabled        BOOLEAN DEFAULT FALSE,
        is_active           BOOLEAN DEFAULT TRUE,
        is_online           BOOLEAN DEFAULT FALSE,
        last_seen_at        TIMESTAMPTZ,
        backup_agent_id     UUID REFERENCES users(id),
        dark_mode           BOOLEAN DEFAULT FALSE,
        created_at          TIMESTAMPTZ DEFAULT NOW(),
        updated_at          TIMESTAMPTZ DEFAULT NOW(),
        deleted_at          TIMESTAMPTZ
    )""")

    # ── 4. role_permissions ───────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS role_permissions (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        role            VARCHAR(20)  NOT NULL,
        permission_key  VARCHAR(100) NOT NULL,
        is_granted      BOOLEAN DEFAULT TRUE,
        updated_by      UUID REFERENCES users(id),
        updated_at      TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE (role, permission_key)
    )""")

    # ── 5. branches ───────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS branches (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name_ar         VARCHAR(150) NOT NULL,
        name_en         VARCHAR(150) NOT NULL,
        code            VARCHAR(20)  UNIQUE NOT NULL,
        city_ar         VARCHAR(100),
        city_en         VARCHAR(100),
        region_ar       VARCHAR(100),
        region_en       VARCHAR(100),
        email           VARCHAR(255),
        phone           VARCHAR(20),
        is_vip          BOOLEAN DEFAULT FALSE,
        is_active       BOOLEAN DEFAULT TRUE,
        internal_notes  TEXT,
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        updated_at      TIMESTAMPTZ DEFAULT NOW(),
        deleted_at      TIMESTAMPTZ
    )""")

    # ── 6. branch_employees ───────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS branch_employees (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        branch_id           UUID REFERENCES branches(id),
        full_name_ar        VARCHAR(150) NOT NULL,
        full_name_en        VARCHAR(150),
        employee_id         VARCHAR(50)  UNIQUE NOT NULL,
        phone               VARCHAR(20),
        email               VARCHAR(255),
        position_ar         VARCHAR(100),
        position_en         VARCHAR(100),
        preferred_language  VARCHAR(5) DEFAULT 'ar'
                            CHECK (preferred_language IN ('ar','en')),
        is_active           BOOLEAN DEFAULT TRUE,
        created_at          TIMESTAMPTZ DEFAULT NOW(),
        updated_at          TIMESTAMPTZ DEFAULT NOW(),
        deleted_at          TIMESTAMPTZ
    )""")

    # ── 7. categories ─────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name_ar         VARCHAR(100) NOT NULL,
        name_en         VARCHAR(100) NOT NULL,
        description_ar  TEXT,
        description_en  TEXT,
        parent_id       UUID REFERENCES categories(id),
        department_id   UUID REFERENCES departments(id),
        icon            VARCHAR(50),
        sort_order      INTEGER DEFAULT 0,
        is_active       BOOLEAN DEFAULT TRUE,
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 8. tags ───────────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name_ar     VARCHAR(50) NOT NULL,
        name_en     VARCHAR(50) NOT NULL,
        color_hex   VARCHAR(7)  DEFAULT '#6B7280',
        created_at  TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 9. tickets ────────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS tickets (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ticket_number       VARCHAR(30) UNIQUE NOT NULL,

        branch_id           UUID REFERENCES branches(id),
        branch_employee_id  UUID REFERENCES branch_employees(id),
        submitter_name_ar   VARCHAR(150),
        submitter_name_en   VARCHAR(150),
        submitter_phone     VARCHAR(20),
        submitter_email     VARCHAR(255),

        category_id         UUID REFERENCES categories(id),
        subject             VARCHAR(255),
        description         TEXT NOT NULL,
        priority            VARCHAR(20) DEFAULT 'medium'
                            CHECK (priority IN ('critical','high','medium','low')),
        status              VARCHAR(30) DEFAULT 'new'
                            CHECK (status IN ('new','open','pending_customer','pending_3rd',
                                              'on_hold','resolved','closed','archived')),

        current_queue       VARCHAR(30) DEFAULT 'main'
                            CHECK (current_queue IN ('main','supervisor','manager')),
        sub_queue_dept_id   UUID REFERENCES departments(id),

        assigned_to         UUID REFERENCES users(id),
        assigned_at         TIMESTAMPTZ,

        parent_ticket_id    UUID,

        channel             VARCHAR(20) DEFAULT 'portal'
                            CHECK (channel IN ('portal','email','whatsapp','phone')),
        source_email_uid    VARCHAR(255),

        sla_policy_id       UUID REFERENCES sla_policies(id),
        sla_deadline        TIMESTAMPTZ,
        sla_paused_at       TIMESTAMPTZ,
        sla_total_paused    INTEGER DEFAULT 0,
        sla_breached        BOOLEAN DEFAULT FALSE,
        sla_notified_75     BOOLEAN DEFAULT FALSE,
        sla_notified_90     BOOLEAN DEFAULT FALSE,
        sla_notified_100    BOOLEAN DEFAULT FALSE,

        first_response_at   TIMESTAMPTZ,
        resolved_at         TIMESTAMPTZ,
        closed_at           TIMESTAMPTZ,
        reopen_count        INTEGER DEFAULT 0,
        total_time_seconds  INTEGER DEFAULT 0,

        csat_token          VARCHAR(100) UNIQUE,
        csat_sent_at        TIMESTAMPTZ,

        locked_by           UUID REFERENCES users(id),
        locked_at           TIMESTAMPTZ,

        version             INTEGER DEFAULT 1,

        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ DEFAULT NOW(),
        deleted_at          TIMESTAMPTZ
    )""")

    # ── 10. ticket_timeline ───────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS ticket_timeline (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ticket_id   UUID NOT NULL,
        event_type  VARCHAR(50) NOT NULL,
        actor_id    UUID REFERENCES users(id),
        actor_type  VARCHAR(20),
        content_ar  TEXT,
        content_en  TEXT,
        is_public   BOOLEAN DEFAULT TRUE,
        metadata    JSONB,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 11. ticket_attachments ────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS ticket_attachments (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ticket_id       UUID NOT NULL,
        timeline_id     UUID REFERENCES ticket_timeline(id),
        file_name       VARCHAR(255) NOT NULL,
        file_size       INTEGER NOT NULL,
        mime_type       VARCHAR(100),
        s3_key          VARCHAR(500) NOT NULL,
        s3_bucket       VARCHAR(100) NOT NULL,
        virus_scanned   BOOLEAN DEFAULT FALSE,
        virus_clean     BOOLEAN,
        uploaded_by     UUID REFERENCES users(id),
        created_at      TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 12. ticket_watchers ───────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS ticket_watchers (
        ticket_id   UUID NOT NULL,
        user_id     UUID REFERENCES users(id) NOT NULL,
        added_at    TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (ticket_id, user_id)
    )""")

    # ── 13. ticket_tags ───────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS ticket_tags (
        ticket_id   UUID NOT NULL,
        tag_id      UUID REFERENCES tags(id) NOT NULL,
        PRIMARY KEY (ticket_id, tag_id)
    )""")

    # ── 14. queue_transfers ───────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS queue_transfers (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ticket_id       UUID NOT NULL,
        from_queue      VARCHAR(30),
        to_queue        VARCHAR(30),
        from_agent_id   UUID REFERENCES users(id),
        to_agent_id     UUID REFERENCES users(id),
        reason          TEXT NOT NULL,
        transferred_by  UUID REFERENCES users(id),
        created_at      TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 15. sla_pauses ────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS sla_pauses (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ticket_id   UUID NOT NULL,
        paused_at   TIMESTAMPTZ NOT NULL,
        resumed_at  TIMESTAMPTZ,
        reason      VARCHAR(50),
        duration_s  INTEGER
    )""")

    # ── 16. csat_surveys ──────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS csat_surveys (
        id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ticket_id               UUID NOT NULL,
        token                   VARCHAR(100) UNIQUE NOT NULL,
        agent_id                UUID REFERENCES users(id),
        rating_overall          SMALLINT CHECK (rating_overall BETWEEN 1 AND 5),
        rating_speed            SMALLINT CHECK (rating_speed BETWEEN 1 AND 5),
        rating_professionalism  SMALLINT CHECK (rating_professionalism BETWEEN 1 AND 5),
        rating_clarity          SMALLINT CHECK (rating_clarity BETWEEN 1 AND 5),
        comments                TEXT,
        submitted_at            TIMESTAMPTZ,
        token_expires_at        TIMESTAMPTZ NOT NULL,
        created_at              TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 17. call_logs ─────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS call_logs (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        agent_id            UUID REFERENCES users(id) NOT NULL,
        branch_employee_id  UUID REFERENCES branch_employees(id),
        caller_phone        VARCHAR(20),
        category_id         UUID REFERENCES categories(id),
        outcome             VARCHAR(30),
        notes               TEXT,
        duration_seconds    INTEGER,
        ticket_id           UUID,
        created_at          TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 18. knowledge_articles ────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_articles (
        id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        title_ar          VARCHAR(200) NOT NULL,
        title_en          VARCHAR(200) NOT NULL,
        content_ar        TEXT NOT NULL,
        content_en        TEXT NOT NULL,
        category_id       UUID REFERENCES categories(id),
        author_id         UUID REFERENCES users(id),
        view_count        INTEGER DEFAULT 0,
        helpful_count     INTEGER DEFAULT 0,
        not_helpful_count INTEGER DEFAULT 0,
        is_published      BOOLEAN DEFAULT FALSE,
        created_at        TIMESTAMPTZ DEFAULT NOW(),
        updated_at        TIMESTAMPTZ DEFAULT NOW(),
        deleted_at        TIMESTAMPTZ
    )""")

    # ── 19. canned_responses ──────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS canned_responses (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        shortcut    VARCHAR(50) NOT NULL UNIQUE,
        name_ar     VARCHAR(100) NOT NULL,
        name_en     VARCHAR(100) NOT NULL,
        content_ar  TEXT NOT NULL,
        content_en  TEXT NOT NULL,
        created_by  UUID REFERENCES users(id),
        is_active   BOOLEAN DEFAULT TRUE,
        created_at  TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 20. system_alerts ─────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS system_alerts (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        title_ar    VARCHAR(200) NOT NULL,
        title_en    VARCHAR(200) NOT NULL,
        message_ar  TEXT NOT NULL,
        message_en  TEXT NOT NULL,
        severity    VARCHAR(20) DEFAULT 'warning'
                    CHECK (severity IN ('info','warning','critical')),
        is_active   BOOLEAN DEFAULT TRUE,
        starts_at   TIMESTAMPTZ DEFAULT NOW(),
        ends_at     TIMESTAMPTZ,
        created_by  UUID REFERENCES users(id),
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        updated_at  TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 21. system_statuses ───────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS system_statuses (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        system_name_ar  VARCHAR(100) NOT NULL,
        system_name_en  VARCHAR(100) NOT NULL,
        status          VARCHAR(20) DEFAULT 'operational'
                        CHECK (status IN ('operational','degraded','partial_outage','major_outage')),
        description_ar  VARCHAR(255),
        description_en  VARCHAR(255),
        eta_minutes     INTEGER,
        sort_order      INTEGER DEFAULT 0,
        updated_by      UUID REFERENCES users(id),
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 22. incidents ─────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS incidents (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        system_id       UUID REFERENCES system_statuses(id),
        title_ar        VARCHAR(200) NOT NULL,
        title_en        VARCHAR(200) NOT NULL,
        description_ar  TEXT,
        description_en  TEXT,
        status          VARCHAR(20) DEFAULT 'investigating'
                        CHECK (status IN ('investigating','identified','monitoring','resolved')),
        started_at      TIMESTAMPTZ NOT NULL,
        resolved_at     TIMESTAMPTZ,
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 23. scheduled_maintenance ─────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS scheduled_maintenance (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        title_ar        VARCHAR(200) NOT NULL,
        title_en        VARCHAR(200) NOT NULL,
        description_ar  TEXT,
        description_en  TEXT,
        starts_at       TIMESTAMPTZ NOT NULL,
        ends_at         TIMESTAMPTZ NOT NULL,
        created_by      UUID REFERENCES users(id),
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 24. automation_rules ──────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS automation_rules (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name_ar         VARCHAR(200) NOT NULL,
        name_en         VARCHAR(200) NOT NULL,
        trigger_type    VARCHAR(50)  NOT NULL,
        conditions      JSONB NOT NULL,
        actions         JSONB NOT NULL,
        priority_order  INTEGER DEFAULT 0,
        is_active       BOOLEAN DEFAULT TRUE,
        execution_count INTEGER DEFAULT 0,
        last_executed   TIMESTAMPTZ,
        created_by      UUID REFERENCES users(id),
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 25. automation_execution_log ──────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS automation_execution_log (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        rule_id     UUID REFERENCES automation_rules(id) NOT NULL,
        ticket_id   UUID,
        success     BOOLEAN NOT NULL,
        error_msg   TEXT,
        executed_at TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 26. form_versions ─────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS form_versions (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        version     INTEGER NOT NULL,
        schema      JSONB NOT NULL,
        is_active   BOOLEAN DEFAULT FALSE,
        published_by UUID REFERENCES users(id),
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        updated_at  TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 27. form_field_definitions ────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS form_field_definitions (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        form_version_id     UUID REFERENCES form_versions(id) NOT NULL,
        field_type          VARCHAR(30) NOT NULL,
        field_key           VARCHAR(50) NOT NULL,
        label_ar            VARCHAR(200) NOT NULL,
        label_en            VARCHAR(200) NOT NULL,
        placeholder_ar      VARCHAR(200),
        placeholder_en      VARCHAR(200),
        is_required         BOOLEAN DEFAULT FALSE,
        sort_order          INTEGER DEFAULT 0,
        validation_rules    JSONB,
        conditional_logic   JSONB,
        options             JSONB
    )""")

    # ── 28. gamification_badges ───────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS gamification_badges (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name_ar         VARCHAR(100) NOT NULL,
        name_en         VARCHAR(100) NOT NULL,
        description_ar  TEXT,
        description_en  TEXT,
        icon_emoji      VARCHAR(10),
        criteria        JSONB NOT NULL,
        is_active       BOOLEAN DEFAULT TRUE,
        created_at      TIMESTAMPTZ DEFAULT NOW(),
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 29. user_badges ───────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS user_badges (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id     UUID REFERENCES users(id) NOT NULL,
        badge_id    UUID REFERENCES gamification_badges(id) NOT NULL,
        ticket_id   UUID,
        awarded_at  TIMESTAMPTZ DEFAULT NOW(),
        awarded_by  UUID REFERENCES users(id)
    )""")

    # ── 30. leaderboard_snapshots ─────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id             UUID REFERENCES users(id) NOT NULL,
        period_type         VARCHAR(20) NOT NULL
                            CHECK (period_type IN ('daily','weekly','monthly','yearly')),
        period_start        DATE NOT NULL,
        tickets_resolved    INTEGER DEFAULT 0,
        avg_resolution_min  FLOAT DEFAULT 0,
        csat_avg            FLOAT DEFAULT 0,
        sla_compliance_pct  FLOAT DEFAULT 0,
        fcr_pct             FLOAT DEFAULT 0,
        rank                INTEGER,
        computed_at         TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 31. employee_of_month ─────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS employee_of_month (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id          UUID REFERENCES users(id) NOT NULL,
        month            DATE NOT NULL,
        is_auto_selected BOOLEAN DEFAULT TRUE,
        announced_at     TIMESTAMPTZ,
        created_at       TIMESTAMPTZ DEFAULT NOW(),
        updated_at       TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 32. themes ────────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS themes (
        id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name_ar             VARCHAR(100) NOT NULL,
        name_en             VARCHAR(100) NOT NULL,
        description_ar      TEXT,
        description_en      TEXT,
        icon_emoji          VARCHAR(10),
        primary_color       VARCHAR(7) NOT NULL,
        secondary_color     VARCHAR(7) NOT NULL,
        background_color    VARCHAR(7),
        logo_s3_key         VARCHAR(500),
        bg_pattern_s3_key   VARCHAR(500),
        bg_opacity          FLOAT DEFAULT 0.2,
        welcome_message_ar  VARCHAR(200),
        welcome_message_en  VARCHAR(200),
        custom_css          TEXT,
        starts_at           TIMESTAMPTZ NOT NULL,
        ends_at             TIMESTAMPTZ NOT NULL,
        is_active           BOOLEAN DEFAULT FALSE,
        auto_activate       BOOLEAN DEFAULT TRUE,
        created_by          UUID REFERENCES users(id),
        created_at          TIMESTAMPTZ DEFAULT NOW(),
        updated_at          TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 33. branding_config ───────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS branding_config (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        logo_s3_key      VARCHAR(500),
        favicon_s3_key   VARCHAR(500),
        primary_color    VARCHAR(7) DEFAULT '#0066CC',
        secondary_color  VARCHAR(7) DEFAULT '#C8215D',
        background_color VARCHAR(7) DEFAULT '#FFFFFF',
        text_color       VARCHAR(7) DEFAULT '#1A1A1A',
        font_arabic      VARCHAR(100) DEFAULT 'Tajawal',
        font_latin       VARCHAR(100) DEFAULT 'Inter',
        custom_css       TEXT,
        updated_by       UUID REFERENCES users(id),
        updated_at       TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 34. integration_configs ───────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS integration_configs (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        key          VARCHAR(50) UNIQUE NOT NULL,
        value_enc    TEXT,
        is_test_mode BOOLEAN DEFAULT FALSE,
        updated_by   UUID REFERENCES users(id),
        updated_at   TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 35. api_keys ──────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS api_keys (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name_ar      VARCHAR(100),
        name_en      VARCHAR(100),
        key_hash     VARCHAR(255) NOT NULL,
        last_4       VARCHAR(4),
        created_by   UUID REFERENCES users(id),
        last_used_at TIMESTAMPTZ,
        expires_at   TIMESTAMPTZ,
        is_active    BOOLEAN DEFAULT TRUE,
        created_at   TIMESTAMPTZ DEFAULT NOW(),
        updated_at   TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 36. audit_log (IMMUTABLE) ─────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        actor_id      UUID REFERENCES users(id),
        actor_ip      INET,
        actor_role    VARCHAR(20),
        action        VARCHAR(100) NOT NULL,
        resource_type VARCHAR(50),
        resource_id   UUID,
        old_value     JSONB,
        new_value     JSONB,
        metadata      JSONB,
        created_at    TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 37. sessions ──────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id        UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
        token_hash     VARCHAR(255) NOT NULL,
        ip_address     INET,
        user_agent     TEXT,
        created_at     TIMESTAMPTZ DEFAULT NOW(),
        expires_at     TIMESTAMPTZ NOT NULL,
        last_active_at TIMESTAMPTZ DEFAULT NOW(),
        is_valid       BOOLEAN DEFAULT TRUE
    )""")

    # ── 38. feature_flags ─────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS feature_flags (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        key        VARCHAR(100) UNIQUE NOT NULL,
        name_ar    VARCHAR(200),
        name_en    VARCHAR(200),
        is_enabled BOOLEAN DEFAULT TRUE,
        updated_by UUID REFERENCES users(id),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 39. notifications ─────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id    UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
        title_ar   VARCHAR(200) NOT NULL,
        title_en   VARCHAR(200) NOT NULL,
        body_ar    TEXT,
        body_en    TEXT,
        type       VARCHAR(50),
        ticket_id  UUID,
        is_read    BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 40. notification_rules ────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS notification_rules (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        event_type   VARCHAR(50) NOT NULL,
        target_roles VARCHAR[] NOT NULL,
        channels     VARCHAR[] NOT NULL,
        template_key VARCHAR(100),
        is_active    BOOLEAN DEFAULT TRUE,
        created_at   TIMESTAMPTZ DEFAULT NOW(),
        updated_at   TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 41. agent_schedules ───────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS agent_schedules (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id    UUID REFERENCES users(id) NOT NULL,
        week_start DATE NOT NULL,
        schedule   JSONB NOT NULL,
        created_by UUID REFERENCES users(id),
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE (user_id, week_start)
    )""")

    # ── 42. shift_swaps ───────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS shift_swaps (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        requester_id UUID REFERENCES users(id) NOT NULL,
        requested_id UUID REFERENCES users(id) NOT NULL,
        swap_date    DATE NOT NULL,
        status       VARCHAR(20) DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','rejected')),
        approved_by  UUID REFERENCES users(id),
        created_at   TIMESTAMPTZ DEFAULT NOW(),
        updated_at   TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 43. leave_requests ────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS leave_requests (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id     UUID REFERENCES users(id) NOT NULL,
        start_date  DATE NOT NULL,
        end_date    DATE NOT NULL,
        reason_ar   TEXT,
        reason_en   TEXT,
        status      VARCHAR(20) DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected')),
        approved_by UUID REFERENCES users(id),
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        updated_at  TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 44. holidays ──────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS holidays (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name_ar      VARCHAR(100) NOT NULL,
        name_en      VARCHAR(100) NOT NULL,
        date         DATE NOT NULL UNIQUE,
        is_recurring BOOLEAN DEFAULT FALSE,
        created_at   TIMESTAMPTZ DEFAULT NOW(),
        updated_at   TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 45. scheduled_reports ─────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS scheduled_reports (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name_ar       VARCHAR(200) NOT NULL,
        name_en       VARCHAR(200) NOT NULL,
        report_config JSONB NOT NULL,
        frequency     VARCHAR(20) NOT NULL
                      CHECK (frequency IN ('daily','weekly','monthly')),
        cron_expr     VARCHAR(100) NOT NULL,
        recipients    VARCHAR[],
        format        VARCHAR(10) DEFAULT 'pdf'
                      CHECK (format IN ('pdf','csv','xlsx')),
        language      VARCHAR(5) DEFAULT 'ar'
                      CHECK (language IN ('ar','en')),
        is_active     BOOLEAN DEFAULT TRUE,
        last_sent_at  TIMESTAMPTZ,
        created_by    UUID REFERENCES users(id),
        created_at    TIMESTAMPTZ DEFAULT NOW(),
        updated_at    TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 46. time_tracking ─────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS time_tracking (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ticket_id  UUID NOT NULL,
        user_id    UUID REFERENCES users(id) NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        ended_at   TIMESTAMPTZ,
        duration_s INTEGER,
        notes_ar   TEXT,
        notes_en   TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 47. follow_ups ────────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS follow_ups (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        ticket_id     UUID NOT NULL,
        scheduled_for TIMESTAMPTZ NOT NULL,
        notes_ar      TEXT,
        notes_en      TEXT,
        created_by    UUID REFERENCES users(id),
        completed_at  TIMESTAMPTZ,
        created_at    TIMESTAMPTZ DEFAULT NOW(),
        updated_at    TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 48. ip_whitelist ──────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS ip_whitelist (
        id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        cidr       INET NOT NULL,
        label_ar   VARCHAR(100),
        label_en   VARCHAR(100),
        added_by   UUID REFERENCES users(id),
        created_at TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 49. email_ingestion_log ───────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS email_ingestion_log (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        message_uid  VARCHAR(255) NOT NULL UNIQUE,
        from_address VARCHAR(255),
        subject      VARCHAR(500),
        ticket_id    UUID,
        action       VARCHAR(30),
        error_msg    TEXT,
        processed_at TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ── 50. system_health_snapshots ───────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS system_health_snapshots (
        id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        db_response_ms   INTEGER,
        redis_ms         INTEGER,
        celery_workers   INTEGER,
        disk_usage_pct   FLOAT,
        memory_usage_pct FLOAT,
        cpu_usage_pct    FLOAT,
        recorded_at      TIMESTAMPTZ DEFAULT NOW()
    )""")

    # ══════════════════════════════════════════════════════════════════════════
    # INDEXES
    # ══════════════════════════════════════════════════════════════════════════

    # users
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_role ON users(role)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_is_active ON users(is_active)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_department_id ON users(department_id)")

    # tickets (on each partition — PG propagates automatically for PARTITION BY RANGE)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_status ON tickets(status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_priority ON tickets(priority)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_assigned_to ON tickets(assigned_to)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_branch_id ON tickets(branch_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_category_id ON tickets(category_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_current_queue ON tickets(current_queue)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_sla_deadline ON tickets(sla_deadline)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_created_at ON tickets(created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_deleted_at ON tickets(deleted_at) WHERE deleted_at IS NULL")

    # Full-text / trigram search on ticket description (Arabic + English)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tickets_description_trgm ON tickets USING gin(description gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_kb_title_ar_trgm ON knowledge_articles USING gin(title_ar gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_kb_title_en_trgm ON knowledge_articles USING gin(title_en gin_trgm_ops)")

    # ticket_timeline
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_timeline_ticket_id ON ticket_timeline(ticket_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_timeline_event_type ON ticket_timeline(event_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_timeline_created_at ON ticket_timeline(created_at)")

    # sessions
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_is_valid ON sessions(is_valid)")

    # audit_log
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_actor_id ON audit_log(actor_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_action ON audit_log(action)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log(created_at)")

    # notifications
    op.execute("CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notifications_is_read ON notifications(is_read)")

    # leaderboard
    op.execute("CREATE INDEX IF NOT EXISTS ix_leaderboard_user_period ON leaderboard_snapshots(user_id, period_type, period_start)")

    # ══════════════════════════════════════════════════════════════════════════
    # SECURITY: Revoke DELETE and UPDATE on audit_log
    # The DB role 'mobily' (app user) must not be able to modify audit entries.
    # ══════════════════════════════════════════════════════════════════════════
    op.execute("REVOKE DELETE ON audit_log FROM mobily")
    op.execute("REVOKE UPDATE ON audit_log FROM mobily")

    # ══════════════════════════════════════════════════════════════════════════
    # DEFAULT DATA: Insert initial branding_config row
    # ══════════════════════════════════════════════════════════════════════════
    op.execute("""
    INSERT INTO branding_config (primary_color, secondary_color)
    VALUES ('#0066CC', '#C8215D')
    ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    # Drop in reverse dependency order
    tables = [
        "system_health_snapshots", "email_ingestion_log", "ip_whitelist",
        "follow_ups", "time_tracking", "scheduled_reports", "holidays",
        "leave_requests", "shift_swaps", "agent_schedules", "notification_rules",
        "notifications", "feature_flags", "sessions", "audit_log", "api_keys",
        "integration_configs", "branding_config", "themes", "employee_of_month",
        "leaderboard_snapshots", "user_badges", "gamification_badges",
        "form_field_definitions", "form_versions", "automation_execution_log",
        "automation_rules", "scheduled_maintenance", "incidents", "system_statuses",
        "system_alerts", "canned_responses", "knowledge_articles", "call_logs",
        "csat_surveys", "sla_pauses", "queue_transfers", "ticket_tags",
        "ticket_watchers", "ticket_attachments", "ticket_timeline",
        "tickets_2028", "tickets_2027", "tickets_2026", "tickets_2025", "tickets",
        "tags", "categories", "branch_employees", "branches",
        "role_permissions", "users", "sla_policies", "departments",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
