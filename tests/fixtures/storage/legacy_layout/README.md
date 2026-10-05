# Store file in the layout written before WP-1.9 (SYNTHETIC)

`raw/77678271/2026.csv` is a **synthetic** partition file of the measurement store in the
layout written before WP-1.9 (`timestamp_utc,temp_c,rh_pct,source`, without the precipitation
and battery columns). The values are invented for the test and are not measurements.

It checks that the store still reads such files (precipitation and battery as `NaN`), leaves
them untouched when an append changes nothing, and rewrites them in the current layout
(`timestamp_utc,temp_c,rh_pct,precip_mm,precip_total_mm,battery_v,source`) when an append
fills in the new columns. Test: `tests/storage/test_auxiliary_columns.py`.
