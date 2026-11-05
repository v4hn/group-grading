"""Markdown reports and ZIP bundles for students."""

from __future__ import annotations

import csv
import io
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .scoring import student_results
from .storage import Course, NotFound


def _fmt(n: float | int | None) -> str:
    return "–" if n is None else str(n)


def display_name(student: dict[str, str]) -> str:
    return f"{student['first_name']} {student['name']}".strip()


def student_folder(student: dict[str, str]) -> str:
    return re.sub(r"[^\w.-]+", "_", f"{student['id']}_{display_name(student)}").strip("_")


def _get_student(course: Course, student_id: str) -> dict[str, str]:
    student = course.student_map().get(student_id)
    if not student:
        raise NotFound("Unknown student")
    return student


def student_report(course: Course, student_id: str, submission_id: str | None = None) -> str:
    student = _get_student(course, student_id)
    names = course.student_map()
    results = student_results(course, student_id)
    if submission_id is not None:
        results = [r for r in results if r["submission_id"] == submission_id]
        if not results:
            raise NotFound("Student is not part of this submission")
    graded = [r for r in results if r["graded"]]
    total = sum(r["total"] for r in graded)
    maximum = sum(r["max"] for r in graded)

    out = [f"# Report Review for {display_name(student)} ({student['id']})", ""]
    if graded:
        pct = f" ({100 * total / maximum:.1f}%)" if maximum else ""
        out += [f"**Total: {total} / {maximum} points{pct}**", ""]
    else:
        out += ["_No graded submissions yet._", ""]

    for r in graded:
        out += [f"## {r['assignment']}", ""]
        others = [display_name(names[s]) for s in r["group"] if s != student_id and s in names]
        if others:
            out += [f"Group: {', '.join(others)}, {display_name(student)}", ""]
        if r["files"]:
            out += ["Submitted files: " + ", ".join(f"`{f}`" for f in r["files"]), ""]
        weighted = any(t["weight"] != 1 for t in r["tasks"])
        out += ["| Task | Weight | Points |", "|---|---:|---:|"] if weighted else ["| Task | Points |", "|---|---:|"]
        for t in r["tasks"]:
            weight = f" | {t['weight']}" if weighted else ""
            out.append(f"| {t['task']}{weight} | {_fmt(t['points'])} / {t['max']} |")
        out += [f"| **Total**{' |' if weighted else ''} | **{r['total']} / {r['max']}** |", ""]
        for t in r["tasks"]:
            if t["feedback"].strip():
                out += [f"### {t['task']} ({_fmt(t['points'])} / {t['max']})", "", t["feedback"].strip(), ""]
        if r["general_feedback"].strip():
            out += ["### General feedback", "", r["general_feedback"].strip(), ""]
    return "\n".join(out).rstrip() + "\n"


def _write_student(course: Course, zf: zipfile.ZipFile, student_id: str, prefix: str) -> None:
    zf.writestr(f"{prefix}report.md", student_report(course, student_id))
    for r in student_results(course, student_id):
        for name in r["files"]:
            path = course.file_path(r["submission_id"], name)
            zf.write(path, f"{prefix}{r['assignment']}/{name}")


def _new_zip() -> tuple[Path, zipfile.ZipFile]:
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    return Path(tmp.name), zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED)


def student_zip(course: Course, student_id: str) -> tuple[Path, str]:
    student = _get_student(course, student_id)
    path, zf = _new_zip()
    with zf:
        _write_student(course, zf, student_id, "")
    return path, f"{student_folder(student)}.zip"


def all_students_zip(course: Course) -> Path:
    path, zf = _new_zip()
    with zf:
        for student in course.students():
            if student_results(course, student["id"]):
                _write_student(course, zf, student["id"], f"{student_folder(student)}/")
    return path


def overview_csv(data: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    names = [a["name"] for a in data["assignments"]]
    w.writerow(["ID", "Name", "First Name", *names, "Total", "Max", "Percent"])
    for row in data["rows"]:
        s = row["student"]
        cells = [
            "" if (c := row["assignments"].get(a)) is None or c["points"] is None else c["points"]
            for a in names
        ]
        w.writerow(
            [s["id"], s["name"], s["first_name"], *cells, row["total"], row["max"],
             "" if row["percent"] is None else row["percent"]]
        )
    return buf.getvalue()
