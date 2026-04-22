"""
Date helper utilities.

Key concept — Wage Month vs Current Month:
==========================================
In Indian payroll compliance (EPF / ESIC / PT / TDS):
  - Contributions are paid for the WAGE MONTH (the month the employee worked).
  - Wage month is the PREVIOUS calendar month relative to today.
  - You cannot pay contributions in advance for a running month.

Example: Today = 21-Apr-2026
  - Wage month  = March 2026      (wages earned, now filing & paying)
  - Due month   = April 2026      (when filing deadline is 15-April)
  - You CANNOT process April 2026 wages yet because April isn't over.

All default month pickers throughout the app should use WAGE MONTH, not
the current calendar month, so users start from the correct default.
"""

from datetime import date


def current_wage_month(today=None):
    """Return (year, month) tuple of the current wage month.

    Wage month = PREVIOUS calendar month. Handles Jan → Dec of prev year.

    Args:
        today: optional date for testing (defaults to today)

    Returns:
        tuple (year, month) — e.g., (2026, 3) if today is April 2026.
    """
    d = today or date.today()
    if d.month == 1:
        return (d.year - 1, 12)
    return (d.year, d.month - 1)


def current_wage_month_str():
    """Return current wage month as 'YYYY-MM' string.
    Useful for <input type='month'> default values and URL params."""
    y, m = current_wage_month()
    return f'{y:04d}-{m:02d}'


def current_wage_month_date():
    """Return current wage month as a date object (first day of that month).
    Useful when building date ranges."""
    y, m = current_wage_month()
    return date(y, m, 1)


def current_fy_start_year(today=None):
    """Return the Indian Financial Year start year for today.
    FY 2025-26 starts April 2025. So if today is Feb 2026, start year is 2025.
    """
    d = today or date.today()
    return d.year if d.month >= 4 else d.year - 1
