import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

def get_next_run(now: datetime):
    peak_hours = [0, 9, 12, 15, 18, 21]
    is_peak = now.hour in peak_hours
    interval_minutes = 2 if is_peak else 15

    next_minute = (now.minute // interval_minutes + 1) * interval_minutes
    if next_minute >= 60:
        target = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        target = now.replace(minute=next_minute, second=0, microsecond=0)

    delay = (target - now).total_seconds()
    return target, delay, is_peak, interval_minutes

# Test with various sample times:
test_times = [
    datetime(2026, 10, 21, 15, 14, 30), # 15h14: peak hour 15
    datetime(2026, 10, 21, 15, 59, 10), # 15h59: transition to 16h
    datetime(2026, 10, 21, 16, 5, 0),   # 16h05: normal hour 16
    datetime(2026, 10, 21, 17, 50, 0),  # 17h50: transition to peak 18h
    datetime(2026, 10, 21, 23, 55, 0),  # 23h55: transition to peak 0h
]

for t in test_times:
    target, delay, is_peak, interval = get_next_run(t)
    print(f"Time: {t.strftime('%H:%M:%S')} -> Peak: {is_peak} ({interval}m) -> Next run: {target.strftime('%H:%M:%S')} (in {int(delay)}s)")

now = datetime.now()
target, delay, is_peak, interval = get_next_run(now)
print(f"\nHiện tại: {now.strftime('%H:%M:%S')} -> Tiếp theo: {target.strftime('%H:%M:%S')} ({interval} phút/lần)")
