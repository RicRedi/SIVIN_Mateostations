# -*- coding: utf-8 -*-
"""
Created on Mon Jan  5 17:33:22 2026

@author: rredi
"""

from datetime import datetime

# Příklad dat
timestamps = [
    "5.1.2026 17:33:01",
"5.1.2026 17:02:36",
"5.1.2026 16:32:10",
"5.1.2026 16:01:45",
"5.1.2026 15:31:19",
"5.1.2026 15:00:54",
"5.1.2026 14:30:29",
"5.1.2026 14:00:03",
"5.1.2026 13:29:38",
"5.1.2026 12:59:13",
"5.1.2026 12:28:48",
"5.1.2026 11:58:24",
"5.1.2026 11:27:59",
"5.1.2026 10:57:34",
][::-1]

# Převod stringů na datetime objekty
dates = [datetime.strptime(ts, "%d.%m.%Y %H:%M:%S") for ts in timestamps]

# Výpočet rozdílů mezi po sobě jdoucími časy
time_diffs = []
for i in range(1, len(dates)):
    delta = dates[i] - dates[i-1]
    time_diffs.append({
        "seconds": delta.total_seconds(),
        "minutes": delta.total_seconds() / 60,
        "hours": delta.total_seconds() / 3600
    })

# Výpis výsledků
for i, diff in enumerate(time_diffs, start=1):
    print(f"Rozdíl mezi timestamp {i} a {i-1}: {diff['seconds']} s, "
          f"{diff['minutes']:.2f} min, {diff['hours']:.2f} h")
