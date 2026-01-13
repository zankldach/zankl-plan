import datetime as dt

def last_sunday(year: int, month: int) -> dt.date:
    if month == 12:
        next_month = dt.date(year + 1, 1, 1)
    else:
        next_month = dt.date(year, month + 1, 1)
    last_day = next_month - dt.timedelta(days=1)
    offset = (last_day.weekday() + 1) % 7
    return last_day - dt.timedelta(days=offset)

def is_summer_time_vienna(date: dt.date) -> bool:
    start = last_sunday(date.year, 3)
    end = last_sunday(date.year, 10)
    return date > start and date < end

def workdays_auto_dst(today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    return 4 if is_summer_time_vienna(today) else 5

def current_kw_and_year():
    today = dt.date.today()
    return today.isocalendar().week, today.year

def next_week_if_after_friday_noon(now=None):
    now = now or dt.datetime.now()
    if now.weekday() == 4 and (now.hour >= 12):
        return True
    if now.weekday() >= 5:
        return True
    return False

def kw_date_range(year: int, kw: int, workdays: int = 5):
    d = dt.date.fromisocalendar(year, kw, 1)
    days = [d + dt.timedelta(days=i) for i in range(workdays)]
    return days
# utils.py

import datetime as dt

# … bestehender Code …

def get_year_kw(year: int | None, kw: int | None) -> tuple[int, int]:
    """Wenn year oder kw None sind, setze auf aktuelles Jahr/KW."""
    today = dt.date.today()
    year = year or today.isocalendar()[0]
    kw = kw or today.isocalendar()[1]
    return year, kw
