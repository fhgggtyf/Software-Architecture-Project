# ADR-013: Flash Sale Time Window Logic
**Status:** Accepted  


## Context
Products need temporary discounted prices during specific time windows (flash sales). System must automatically apply correct price based on current time without manual intervention or cron jobs. Requires second-level accuracy during high-traffic sales.

## Decision
Implement real-time time-based price calculation:
- Database fields: flash_sale_price, flash_sale_start, flash_sale_end in Product table
- Check timing on every cart operation and display
- Use UTC for all timestamps to avoid timezone issues
- Dynamic pricing: Calculate effective price at runtime
- Implementation: app.py (lines 95-110), app_web.py (lines 250-280)

```python
from datetime import datetime, UTC

# Determine effective price
unit_price = p.price  # Default to regular price
if p.flash_sale_price and p.flash_sale_start and p.flash_sale_end:
    start = datetime.fromisoformat(p.flash_sale_start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(p.flash_sale_end).replace(tzinfo=UTC)
    now = datetime.now(UTC)
    
    if start <= now <= end:
        unit_price = p.flash_sale_price  # Apply flash price
```

## Consequences
**Positive:**
- Automatic price switching - no manual intervention
- Real-time accuracy - correct to the second
- No cron jobs or background tasks needed
- Clear visual indication in UI (strikethrough original price)

**Negative:**
- Calculation on every request (~1ms overhead, acceptable)
- Requires accurate server clock (standard practice)
- Timezone handling requires care (mitigated by UTC everywhere)

**Trade-offs:**
- Runtime calculation vs pre-computed: Chose runtime for accuracy and simplicity
- UTC vs local time: Chose UTC to avoid daylight saving and timezone complexity

## Alternatives Considered
- **Cron Job to Update Prices** - Rejected: Not real-time (minute-level granularity); requires scheduler infrastructure
- **Manual Price Updates** - Rejected: Error-prone; doesn't scale to 100+ flash sales
