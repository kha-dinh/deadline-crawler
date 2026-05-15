---
name: POPL shepherd false positive
description: V14 date-order warning on POPL is a known false positive due to POPL's early shepherd assignment process
type: project
---

V14 checker warns: `POPL: date order: notification (2025-11-06 23:59) > shepherd (2025-10-02 23:59)`

This is a false positive. POPL assigns shepherds *before* the final notification (early shepherd contact is part of their review process). The data is correct; our canonical LABEL_ORDER assumes shepherd comes after notification, which is the standard flow but not POPL's.

**Why:** POPL uses a non-standard peer-shepherding model where shepherd assignment precedes the author notification date.

**How to apply:** Do not attempt to fix this warning by changing the data or reordering labels. If V14 is extended to support per-conference ordering exceptions, POPL is the motivating case.
