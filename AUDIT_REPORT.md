# تقرير المراجعة الشاملة — نظام موبايلي للدعم التقني

تم إجراء مراجعة شاملة للنظام بناءً على فحص الكود والتحليل الآلي. النتائج مصنفة حسب الخطورة.

---

## 🔴 عالية الخطورة (يجب إصلاحها فوراً)

### 1. أخطاء في أسماء الأعمدة/الخصائص

| الملف | السطر | المشكلة | التصحيح |
|-------|-------|---------|---------|
| `app/api/portal.py` | 171 | `Category.display_order` غير موجود | استخدم `Category.sort_order` |
| `app/api/supervisor.py` | 675 | `Ticket.queue_level` غير موجود | Ticket يستخدم `current_queue` (نص) وليس queue_level (رقم) |
| `app/api/supervisor.py` | 742 | `ticket.assignee_id` غير موجود | استخدم `ticket.assigned_to` |
| `app/api/supervisor.py` | 772 | `User.branch_id` غير موجود | User لديه `department_id` فقط؛ للبث حسب الفرع استخدم BranchEmployee أو علاقة أخرى |
| `app/templates/supervisor/tickets.html` | 124 | `ticket.queue_level` | استخدم `ticket.current_queue` |

### 2. تعارض استدعاء create_ticket

| الملف | السطر | المشكلة |
|-------|-------|---------|
| `app/services/whatsapp.py` | 155-165 | `create_ticket` يتوقع `form: TicketSubmitForm` لكن يُستدعى بـ kwargs مباشرة — سيفشل بـ TypeError |
| `app/worker/tasks/email_ingestion.py` | ~106 | نفس المشكلة |

**الحل:** إنشاء `TicketSubmitForm` من القيم قبل الاستدعاء.

### 3. ثغرة Open Redirect

| الملف | السطر | المشكلة |
|-------|-------|---------|
| `app/api/language.py` | 19-21 | `redirect_to.startswith("/")` يقبل `//evil.com` — ثغرة إعادة توجيه مفتوحة |

**الحل:** التحقق من أن المسار يبدأ بـ `/` ولا يبدأ بـ `//`، أو استخدام قائمة مسارات مسموحة.

### 4. API بدون مصادقة

| الملف | السطر | المشكلة |
|-------|-------|---------|
| `app/api/dashboard.py` | 666 | `GET /api/kb/search` — يسمح بالوصول لمقالات KB الداخلية بدون تسجيل دخول |

**الحل:** إضافة `require_permission("kb.view")` أو التحقق من المستخدم.

### 5. تعارض User.department_id مع UserDepartment

| الملف | السطر | المشكلة |
|-------|-------|---------|
| `app/services/queue.py` | 212 | `auto_balance` يفلتر بـ `User.department_id` فقط |
| `app/services/kpi.py` | 183 | `get_team_workload` نفس المشكلة |
| `app/api/supervisor.py` | 156, 299, 687 | فلترة الوكلاء بـ `User.department_id` فقط |

الموظفون المعيّنون لأقسام متعددة عبر `UserDepartment` قد يُستبعدون إذا كان `department_id` الأساسي مختلفاً.

---

## 🟠 متوسطة الخطورة

### 6. db.begin() مع get_db

استخدام `async with db.begin()` داخل routes تستخدم `Depends(get_db)` قد يسبب تعارضاً في إدارة المعاملات.

**الملفات المتأثرة:** dashboard.py, portal.py, supervisor.py, manager.py, admin.py, whatsapp.py

### 7. Webhooks بدون التحقق من التوقيع

| الملف | المشكلة |
|-------|---------|
| `app/api/webhooks.py` | webhook البريد الإلكتروني لا يتحقق من التوقيع — أي شخص يمكنه إرسال POST |

### 8. استثناءات تُبتلع

| الملف | السطر | المشكلة |
|-------|-------|---------|
| `app/api/dashboard.py` | 822-826, 841-845 | `except Exception: pass` مع إرجاع `{"ok": True}` — يخفي الأخطاء |

### 9. سباق في claim_ticket

`claim_ticket` يستخدم SELECT ثم UPDATE بدون قفل — طلبان متزامنان قد يستلمان نفس التذكرة.

---

## 🟡 منخفضة الخطورة

### 10. نقص require_permission في بعض الـ endpoints

عدد من الـ endpoints تعتمد على `request.state.user` فقط بدون `require_permission` (claim, call-log, notifications, profile, SSE).

### 11. تناقض في تنسيق الاستجابات

اختلاف في شكل JSON بين الـ endpoints (مثلاً `{"ok": true}` vs `{"results": []}`).

### 12. فهارس مفقودة

أعمدة تُستعلم عنها كثيراً بدون فهارس: `sub_queue_dept_id`, `user_session.expires_at`, إلخ.

---

## ملخص الإجراءات الموصى بها

1. **فوري:** إصلاح أسماء الأعمدة الخاطئة (display_order, queue_level, assignee_id, branch_id).
2. **فوري:** إصلاح استدعاءات `create_ticket` في whatsapp و email_ingestion.
3. **فوري:** إصلاح ثغرة Open Redirect في language toggle.
4. **فوري:** إضافة مصادقة لـ `/api/kb/search`.
5. **قريباً:** توحيد استخدام `UserDepartment` بدلاً من `User.department_id` حيث ينطبق.
6. **لاحقاً:** مراجعة استخدام `db.begin()` وإدارة المعاملات.
7. **لاحقاً:** إضافة قفل أو `SELECT FOR UPDATE` في `claim_ticket`.
8. **لاحقاً:** التحقق من توقيع Webhooks.

---

*تم إنشاء هذا التقرير بناءً على مراجعة شاملة للنظام.*
