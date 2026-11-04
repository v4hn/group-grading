"""Compute effective points per student from group grades and overrides."""

from __future__ import annotations

from typing import Any

from .storage import Course


def _num(value: float | int) -> float | int:
    return int(value) if float(value).is_integer() else round(float(value), 2)


def student_result(
    submission: dict[str, Any], student_id: str, tasks: dict[str, float | int]
) -> dict[str, Any]:
    override = submission.get("overrides", {}).get(student_id, {})
    group = submission.get("grades", {})
    rows = []
    total = 0
    graded = False
    for task, maximum in tasks.items():
        g = group.get(task, {})
        o = override.get(task, {})
        points = o.get("points") if o.get("points") is not None else g.get("points")
        feedback = o.get("feedback") or g.get("feedback") or ""
        if points is not None:
            graded = True
            total += points
        rows.append(
            {
                "task": task,
                "max": maximum,
                "points": points,
                "feedback": feedback,
                "overridden": bool(o.get("points") is not None or o.get("feedback")),
            }
        )
    return {
        "submission_id": submission["id"],
        "assignment": submission["assignment"],
        "created": submission.get("created", ""),
        "files": submission.get("files", []),
        "general_feedback": submission.get("general_feedback", ""),
        "group": submission.get("students", []),
        "tasks": rows,
        "total": _num(total),
        "max": _num(sum(tasks.values())),
        "graded": graded,
    }


def student_results(course: Course, student_id: str) -> list[dict[str, Any]]:
    """All of a student's submissions in creation order."""
    all_tasks = course.tasks()
    return [
        student_result(s, student_id, all_tasks.get(s["assignment"], {}))
        for s in course.list_submissions()
        if student_id in s["students"]
    ]


def overview(course: Course) -> dict[str, Any]:
    tasks = course.tasks()
    submissions = course.list_submissions()
    rows = []
    for student in course.students():
        sid = student["id"]
        per_assignment: dict[str, Any] = {}
        for sub in submissions:
            if sid not in sub["students"]:
                continue
            res = student_result(sub, sid, tasks.get(sub["assignment"], {}))
            previous = per_assignment.get(sub["assignment"])
            # The latest submission wins; earlier ones are reported as duplicates.
            res["duplicates"] = (previous["duplicates"] + [previous["submission_id"]]) if previous else []
            per_assignment[sub["assignment"]] = res
        cells = {
            a: {
                "submission_id": r["submission_id"],
                "points": r["total"] if r["graded"] else None,
                "max": r["max"],
                "percent": round(100 * r["total"] / r["max"], 1) if r["graded"] and r["max"] else None,
                "duplicates": r["duplicates"],
            }
            for a, r in per_assignment.items()
        }
        graded_cells = [r for r in per_assignment.values() if r["graded"]]
        total = sum(r["total"] for r in graded_cells)
        maximum = sum(r["max"] for r in graded_cells)
        rows.append(
            {
                "student": student,
                "assignments": cells,
                "total": _num(total),
                "max": _num(maximum),
                "percent": round(100 * total / maximum, 1) if maximum else None,
            }
        )
    return {
        "assignments": [{"name": a, "max": _num(sum(t.values()))} for a, t in tasks.items()],
        "rows": rows,
    }
