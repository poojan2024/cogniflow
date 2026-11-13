"""Print the priority algorithm's input factors, score and level for the four test cases (viva demo).

Run from the backend/ folder:   python -m scripts.demo_priority
Needs no database or internet. A fixed "today" (2026-10-07) keeps the output reproducible.
"""
from datetime import date, timedelta

from app.services.priority import calculate_priority

TODAY = date(2026, 10, 7)

CASES = [
    ("1. Far deadline + low importance", dict(days=30, importance=1, status="PENDING", activity=3)),
    ("2. Approaching deadline + high importance", dict(days=3, importance=5, status="PENDING", activity=3)),
    ("3. Overdue + high importance", dict(days=-2, importance=5, status="PENDING", activity=3)),
    ("4. Completed task", dict(days=-2, importance=5, status="COMPLETED", activity=3)),
    ("5. Same as case 1 but manually set to CRITICAL", dict(days=30, importance=1, status="PENDING", activity=3, manual="CRITICAL")),
]


def main() -> None:
    for title, c in CASES:
        r = calculate_priority(
            due_date=TODAY + timedelta(days=c["days"]),
            importance=c["importance"],
            status=c["status"],
            activity_priority=c["activity"],
            today=TODAY,
            manual_priority=c.get("manual"),
        )
        print("=" * 78)
        print(title)
        print(f"  Input : deadline in {c['days']} days, importance {c['importance']}/5, "
              f"activity priority {c['activity']}/5, status {c['status']}")
        for f in r.factors:
            print(f"  {f.name:<18} {f.detail:<22} normalized {f.normalized:.2f} x weight {f.weight:.2f} = {f.points:5.2f} points")
        print(f"  Score : {r.score:.2f} / 100   ->   {r.level}" + ("   (manual override)" if r.is_overridden else ""))
        print(f"  Why   : {r.explanation}")


if __name__ == "__main__":
    main()
