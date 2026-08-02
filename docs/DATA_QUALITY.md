# Data quality (freshness)

Per-type, per-source **freshness** after each analytics pass.  
Not a plausibility checker (stuck values / ranges) — that is deferred.

## What you see

Dashboard **Sensors** strip (today, `source=ring` only): always-on chips  
HR · HRV · Steps · SpO₂ · Stress · Temp. Green = ok, amber = stale.  
Hover for last sample age + reason.

## Observed R09 cadences (prod Jul–Aug 2026)

| Type | Observed p50 | p99 same-day gap | Quirk |
|------|--------------|------------------|--------|
| HR | **15 min** | 75 min | Best worn signal; stall = HR dies while HRV/SpO₂/stress continue |
| HRV | **60 min** | 120 min | |
| SpO₂ | 60 min | 120 min | |
| Steps | ~60 min when moving | **240 min** | Zero hours **omitted**; often stops 1–2h before last HR |
| Stress | 30 min when on | — | **Ends 3–11h before last HR** most nights |
| Temp | 30 min (completed days) | — | **Today empty until late** — normal |

## Rules (summary)

| Case | Result |
|------|--------|
| Temp today, cnt=0 | ok (`temp_pending`) |
| cnt=0, worn, most types | stale (`absent`) |
| Stress cnt=0 early day (few HR samples) | ok (`stress_sparse_ok`) |
| Stress cnt=0, worn, HR samples ≥ 20 | stale (`absent`) |
| HR lags max(HRV,SpO₂,stress) > 90 min | stale (`hr_logger_stall`) |
| HRV/SpO₂ lag behind day's freshest > 150 min while worn | stale (`lag`) |
| Steps lag behind freshest > 300 min, worn, local hour 08–21 | stale (`lag`) |
| All types equally old (hours after last sync, no new data) | **ok** (peer lag 0) |
| Steps evening stop before HR | **ok** (not peer-lagged) |
| Stress ends hours before HR | **ok** (no peer-lag) |
| Not worn (no recent HR) | absent types → ok (`not_worn`) |
| Phone never synced | **no phone rows** |

Sources: only emit sources that appear in raw_* (plus type-missing for primary `ring` on days with other ring data).

## Thresholds

```text
WORN_WINDOW_MIN     = 180   # HR age ⇒ worn
HR_STALL_LAG_MIN    = 90
HRV_SPO2_AGE_MIN    = 150
STEPS_STALL_MIN     = 300   # waking hours only
```

Code: `collector/analytics/data_quality.py`  
Tests: `tests/test_data_quality.py`
