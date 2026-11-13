"""Opt-in isolated performance benchmark for position report aggregation."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import statistics
import subprocess
import time
import tracemalloc
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.db import connection
from django.db.models import Prefetch

from billing import services
from billing.models import AttendanceDay, Charge, MealSignup, Participant, ParticipantFamilyMember
from tests.factories import CampFactory, ParticipantFactory, ParticipantFamilyMemberFactory

REFERENCE_COMMIT = "faad22a18dd610c531752401402df4a4a59afc92"


def calculate_position_report_reference(camp):
    """HEAD reference implementation, retained here only for parity benchmarking."""
    kind_labels = dict(Charge.Kind.choices)
    article_rows = {}
    for charge in Charge.objects.filter(participant__camp=camp, deleted_at__isnull=True):
        key = (charge.kind, charge.position_report_description or charge.description)
        row = article_rows.setdefault(key, {"count": 0, "quantity": services.ZERO, "gross": services.ZERO})
        row["count"] += 1
        row["quantity"] += Decimal(str(charge.quantity))
        row["gross"] += Decimal(str(charge.total))
    articles = [
        services.ArticleUsage(
            kind=kind,
            kind_label=kind_labels.get(kind, kind),
            description=description,
            booking_count=row["count"],
            quantity_total=services.money(row["quantity"]),
            gross_total=services.money(row["gross"]),
        )
        for (kind, description), row in sorted(
            article_rows.items(), key=lambda item: (-item[1]["count"], item[0][0], item[0][1])
        )
    ]
    variant_labels = dict(MealSignup.Variant.choices)
    meal_labels = dict(MealSignup.Meal.choices)
    if camp.starts_on and camp.ends_on and camp.starts_on <= camp.ends_on:
        dates = services.camp_meal_dates(camp)
        signups = MealSignup.objects.filter(
            participant__camp=camp,
            status=MealSignup.Status.ACTIVE,
            meal_date__range=(dates[0], dates[-1]),
        ).values_list("meal", "variant")
    else:
        signups = MealSignup.objects.filter(participant__camp=camp, status=MealSignup.Status.ACTIVE).values_list(
            "meal", "variant"
        )
    meal_rows = {}
    for meal, variant in signups:
        meal_rows.setdefault(meal, {})
        meal_rows[meal][variant] = meal_rows[meal].get(variant, 0) + 1
    meals = [
        services.MealUsage(
            meal=meal,
            meal_label=meal_labels.get(meal, meal),
            variant_counts={
                variant_labels[variant]: meal_rows.get(meal, {}).get(variant, 0)
                for variant in services.MEAL_VARIANT_ORDER
            },
            total=sum(meal_rows.get(meal, {}).values()),
        )
        for meal in (MealSignup.Meal.DINNER, MealSignup.Meal.BREAKFAST)
    ]
    participants = list(
        Participant.objects.filter(camp=camp, archived_at__isnull=True)
        .select_related("camp")
        .prefetch_related(
            Prefetch(
                "attendance_days",
                queryset=AttendanceDay.objects.filter(family_member__isnull=True, is_present=True),
                to_attr=services._ATTENDANCE_PREFETCH_ATTRIBUTE,
            )
        )
    )
    family_members = list(
        ParticipantFamilyMember.objects.filter(guardian__camp=camp, guardian__archived_at__isnull=True, is_active=True)
        .select_related("guardian__camp")
        .prefetch_related(
            Prefetch(
                "attendance_days",
                queryset=AttendanceDay.objects.filter(is_present=True),
                to_attr=services._ATTENDANCE_PREFETCH_ATTRIBUTE,
            )
        )
    )
    attendance_days = [
        services.PositionReportDay(
            day=day,
            participant_count=sum(
                services._covers_day(person.arrival_date, person.departure_date, day) for person in participants
            ),
            family_member_count=sum(
                services._covers_day(
                    member.arrival_date or member.guardian.arrival_date,
                    member.departure_date or member.guardian.departure_date,
                    day,
                )
                for member in family_members
            ),
        )
        for day in services.camp_meal_dates(camp)
    ]
    participant_nights = sum(
        person.effective_attendance_nights
        if person.attendance_tracking_enabled
        else person.actual_nights or person.booked_nights or 0
        for person in participants
    )
    family_member_nights = sum(
        member.effective_attendance_nights if member.attendance_tracking_enabled else member.booked_nights or 0
        for member in family_members
    )
    return services.PositionReport(camp, articles, meals, attendance_days, participant_nights, family_member_nights)


@pytest.mark.position_report_performance
@pytest.mark.django_db(transaction=True)
@pytest.mark.skipif(os.environ.get("POSITION_REPORT_PERFORMANCE") != "1", reason="explicit benchmark run only")
def test_position_report_performance(tmp_path: Path) -> None:
    """Compare the HEAD implementation with the optimized implementation on identical rows."""
    camp = CampFactory(starts_on=date(2026, 7, 1), ends_on=date(2026, 7, 30))
    participants = [
        ParticipantFactory(
            camp=camp,
            first_name=f"Person{index}",
            last_name="Benchmark",
            arrival_date=date(2026, 7, 1),
            departure_date=date(2026, 7, 30),
            attendance_tracking_enabled=index < 100,
        )
        for index in range(1000)
    ]
    family_members = [
        ParticipantFamilyMemberFactory(
            guardian=participants[index],
            first_name=f"Family{index}",
            last_name="Benchmark",
            arrival_date=None if index % 2 else date(2026, 7, 3),
            departure_date=None if index % 2 else date(2026, 7, 27),
            attendance_tracking_enabled=index < 100,
        )
        for index in range(1000)
    ]
    participant_ids = [person.pk for person in participants]
    family_ids = [member.pk for member in family_members]

    # Fixed attendance rows exercise tracked/untracked paths and night handling.
    AttendanceDay.objects.bulk_create(
        [
            AttendanceDay(participant_id=person_id, date=date(2026, 7, 3), is_present=True)
            for person_id in participant_ids
        ]
        + [
            AttendanceDay(
                participant_id=participants[index].pk,
                family_member_id=member_id,
                date=date(2026, 7, 3),
                is_present=True,
            )
            for index, member_id in enumerate(family_ids)
        ]
        + [
            AttendanceDay(participant_id=participant_ids[index], date=date(2026, 7, day), is_present=True)
            for index in range(100)
            for day in (4, 7, 10, 13, 16)
        ]
        + [
            AttendanceDay(
                participant_id=participant_ids[index],
                family_member_id=family_ids[index],
                date=date(2026, 7, day),
                is_present=True,
            )
            for index in range(100)
            for day in (4, 7, 10, 13, 16)
        ],
        batch_size=2000,
    )
    MealSignup.objects.bulk_create(
        [
            MealSignup(
                participant_id=participant_ids[index],
                meal_date=date(2026, 7, 5),
                meal=MealSignup.Meal.DINNER,
                variant=list(MealSignup.Variant.values)[index % len(MealSignup.Variant.values)],
                status=MealSignup.Status.RETRACTED if index < 100 else MealSignup.Status.ACTIVE,
            )
            for index in range(1000)
        ],
        batch_size=2000,
    )

    result: dict[str, object] = {
        "base_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip(),
        "reference_commit": REFERENCE_COMMIT,
        "optimized_code_state": "working tree based on base_commit",
        "optimized_services_sha256": hashlib.sha256(Path("src/billing/services.py").read_bytes()).hexdigest(),
        "worktree_dirty": bool(subprocess.run(["git", "diff", "--quiet"], check=False).returncode),
        "working_tree_status": subprocess.run(
            ["git", "status", "--short", "--untracked-files=no"], check=True, capture_output=True, text=True
        ).stdout.strip(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "database_vendor": connection.vendor,
        "database_driver": connection.Database.__name__,
        "database_sizes_bytes": {},
        "samples": [],
        "budgets": {"optimized_100k_median_seconds_max": 5.0, "optimized_peak_bytes_max": 128 * 1024 * 1024},
    }
    json_path = Path(os.environ.get("POSITION_REPORT_BENCHMARK_JSON", tmp_path / "position-report-benchmark.json"))

    try:
        for target_count in (10_000, 50_000, 100_000):
            current_count = Charge.objects.filter(participant__camp=camp).count()
            to_create = [
                Charge(
                    participant_id=participant_ids[index % len(participant_ids)],
                    kind=Charge.Kind.OTHER,
                    description=f"Benchmark article {index % 100}",
                    quantity=Decimal("1.25"),
                    unit_price=Decimal("3.40"),
                )
                for index in range(current_count, target_count)
            ]
            Charge.objects.bulk_create(to_create, batch_size=2000)
            del to_create

            reference = calculate_position_report_reference(camp)
            actual = services.calculate_position_report(camp)
            assert actual == reference

            # One warmup per implementation, then five independently timed calculations.
            calculate_position_report_reference(camp)
            services.calculate_position_report(camp)
            reference_samples = []
            optimized_samples = []
            for _ in range(5):
                started = time.perf_counter()
                calculate_position_report_reference(camp)
                reference_samples.append(time.perf_counter() - started)
                started = time.perf_counter()
                services.calculate_position_report(camp)
                optimized_samples.append(time.perf_counter() - started)

            tracemalloc.start()
            calculate_position_report_reference(camp)
            _baseline_current, baseline_peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            tracemalloc.start()
            services.calculate_position_report(camp)
            _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute("PRAGMA page_count")
                    page_count = int(cursor.fetchone()[0])
                    cursor.execute("PRAGMA page_size")
                    database_size = page_count * int(cursor.fetchone()[0])
            else:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_database_size(current_database())")
                    database_size = int(cursor.fetchone()[0])
            result["database_sizes_bytes"][str(target_count)] = database_size  # type: ignore[index]
            result["samples"].append(  # type: ignore[union-attr]
                {
                    "charges": target_count,
                    "groups": 100,
                    "participants": 1000,
                    "family_members": 1000,
                    "calendar_days": 30,
                    "baseline_seconds": reference_samples,
                    "optimized_seconds": optimized_samples,
                    "baseline_median_seconds": statistics.median(reference_samples),
                    "optimized_median_seconds": statistics.median(optimized_samples),
                    "baseline_peak_bytes": baseline_peak_bytes,
                    "optimized_peak_bytes": peak_bytes,
                }
            )
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            if target_count == 100_000:
                assert statistics.median(optimized_samples) <= 5.0
                assert peak_bytes <= 128 * 1024 * 1024
    finally:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
