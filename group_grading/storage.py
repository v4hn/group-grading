"""File-based persistence for a course folder."""

from __future__ import annotations

import csv
import io
import math
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

import yaml

MIN_GROUP = 1

_SUBMISSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StorageError(Exception):
    """Invalid request data; mapped to HTTP 400."""


class NotFound(StorageError):
    """Missing entity; mapped to HTTP 404."""


def sanitize_filename(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().lstrip(".")
    if not name:
        raise StorageError("Invalid file name")
    return name[:200]


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "submission"


def _parse_points(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StorageError(f"Invalid points value: {value!r}")
    if not math.isfinite(value) or value < 0:
        raise StorageError(f"Invalid points value: {value!r}")
    return value


def _clean_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise StorageError("Grade entry must be an object")
    feedback = entry.get("feedback", "")
    if not isinstance(feedback, str):
        raise StorageError("Feedback must be a string")
    return {"points": _parse_points(entry.get("points")), "feedback": feedback}


class Course:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).resolve()
        self.submissions_dir = self.root / "submissions"
        self._lock = threading.RLock()
        self.submissions_dir.mkdir(parents=True, exist_ok=True)

    # ---- students / tasks -------------------------------------------------

    def students(self) -> list[dict[str, str]]:
        path = self.root / "students.csv"
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        rows = []
        for row in reader:
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            sid = row.get("id", "")
            if not sid:
                continue
            rows.append(
                {"id": sid, "name": row.get("name", ""), "first_name": row.get("first name", "")}
            )
        return rows

    def student_map(self) -> dict[str, dict[str, str]]:
        return {s["id"]: s for s in self.students()}

    def _task_specs(self) -> dict[str, dict[str, tuple[float | int, float | int]]]:
        """assignment -> task -> (max points, weight); a task is `points` or `{Points, Weight}`."""
        path = self.root / "tasks.yaml"
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise StorageError("tasks.yaml must be a mapping of assignment -> task -> points")
        result: dict[str, dict[str, tuple[float | int, float | int]]] = {}
        for assignment, tasks in data.items():
            if not isinstance(tasks, dict):
                raise StorageError(f"tasks.yaml: '{assignment}' must map task names to points")
            specs = {}
            for task, spec in tasks.items():
                where = f"tasks.yaml: '{assignment}' / '{task}'"
                if isinstance(spec, dict):
                    lowered = {str(k).lower(): v for k, v in spec.items()}
                    unknown = set(lowered) - {"points", "weight"}
                    if unknown or "points" not in lowered:
                        raise StorageError(f"{where} must have 'Points' and optionally 'Weight'")
                    points, weight = lowered["points"], lowered.get("weight", 1)
                else:
                    points, weight = spec, 1
                for label, value in (("Points", points), ("Weight", weight)):
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                        raise StorageError(f"{where}: invalid {label} value {value!r}")
                specs[str(task)] = (points, weight)
            result[str(assignment)] = specs
        return result

    def tasks(self) -> dict[str, dict[str, float | int]]:
        return {a: {t: p for t, (p, _) in specs.items()} for a, specs in self._task_specs().items()}

    def weights(self) -> dict[str, dict[str, float | int]]:
        return {a: {t: w for t, (_, w) in specs.items()} for a, specs in self._task_specs().items()}

    # ---- submissions ------------------------------------------------------

    def _dir(self, sid: str) -> Path:
        if not _SUBMISSION_ID_RE.match(sid):
            raise NotFound("Unknown submission")
        path = (self.submissions_dir / sid).resolve()
        if path.parent != self.submissions_dir or not path.is_dir():
            raise NotFound("Unknown submission")
        return path

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _load(self, sid: str) -> dict[str, Any]:
        d = self._dir(sid)
        meta_path = d / "submission.yaml"
        if not meta_path.exists():
            raise NotFound("Unknown submission")
        data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        data["id"] = sid
        data.setdefault("students", [])
        data.setdefault("general_feedback", "")
        data.setdefault("grades", {})
        data.setdefault("overrides", {})
        data["students"] = [str(s) for s in data["students"]]
        data["files"] = self._list_files(d)
        return data

    def _save(self, data: dict[str, Any]) -> None:
        d = self._dir(data["id"])
        stored = {k: v for k, v in data.items() if k not in ("files", "id")}
        stored = {"id": data["id"], **stored}
        self._write_yaml(d / "submission.yaml", stored)

    @staticmethod
    def _list_files(d: Path) -> list[str]:
        files = d / "files"
        if not files.is_dir():
            return []
        return sorted(p.name for p in files.iterdir() if p.is_file())

    def list_submissions(self) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for d in sorted(self.submissions_dir.iterdir()):
                if d.is_dir() and (d / "submission.yaml").exists():
                    result.append(self._load(d.name))
            result.sort(key=lambda s: (str(s.get("created", "")), s["id"]))
            return result

    def get_submission(self, sid: str) -> dict[str, Any]:
        with self._lock:
            return self._load(sid)

    def _validate_group(self, student_ids: list[str]) -> list[str]:
        ids = [str(s) for s in student_ids]
        if len(set(ids)) != len(ids):
            raise StorageError("Duplicate student in group")
        if len(ids) < MIN_GROUP:
            raise StorageError("A group needs at least one student")
        known = self.student_map()
        unknown = [s for s in ids if s not in known]
        if unknown:
            raise StorageError(f"Unknown student ID(s): {', '.join(unknown)}")
        return ids

    def _validate_assignment(self, assignment: str) -> str:
        if assignment not in self.tasks():
            raise StorageError(f"Unknown assignment: {assignment!r}")
        return assignment

    def create_submission(self, assignment: str, student_ids: list[str]) -> dict[str, Any]:
        with self._lock:
            self._validate_assignment(assignment)
            ids = self._validate_group(student_ids)
            slug = _slug(assignment)
            n = 1
            while (self.submissions_dir / f"{slug}-{n:03d}").exists():
                n += 1
            sid = f"{slug}-{n:03d}"
            d = self.submissions_dir / sid
            (d / "files").mkdir(parents=True)
            data = {
                "id": sid,
                "assignment": assignment,
                "created": datetime.now().isoformat(timespec="seconds"),
                "students": ids,
                "general_feedback": "",
                "grades": {},
                "overrides": {},
            }
            self._write_yaml(d / "submission.yaml", data)
            return self._load(sid)

    def update_submission(
        self, sid: str, assignment: str | None, student_ids: list[str] | None
    ) -> dict[str, Any]:
        with self._lock:
            data = self._load(sid)
            if assignment is not None:
                data["assignment"] = self._validate_assignment(assignment)
            if student_ids is not None:
                data["students"] = self._validate_group(student_ids)
                data["overrides"] = {
                    s: o for s, o in data["overrides"].items() if s in data["students"]
                }
            self._save(data)
            return self._load(sid)

    def delete_submission(self, sid: str) -> None:
        with self._lock:
            shutil.rmtree(self._dir(sid))

    # ---- files ------------------------------------------------------------

    def add_file(self, sid: str, filename: str, fileobj: BinaryIO) -> str:
        with self._lock:
            files_dir = self._dir(sid) / "files"
            files_dir.mkdir(exist_ok=True)
            name = sanitize_filename(filename)
            stem, suffix = Path(name).stem, Path(name).suffix
            candidate, n = name, 1
            while (files_dir / candidate).exists():
                n += 1
                candidate = f"{stem} ({n}){suffix}"
            with open(files_dir / candidate, "xb") as out:
                shutil.copyfileobj(fileobj, out)
            return candidate

    def file_path(self, sid: str, filename: str) -> Path:
        files_dir = self._dir(sid) / "files"
        path = (files_dir / filename).resolve()
        if path.parent != files_dir.resolve() or not path.is_file():
            raise NotFound("Unknown file")
        return path

    def delete_file(self, sid: str, filename: str) -> None:
        with self._lock:
            self.file_path(sid, filename).unlink()

    # ---- grades -----------------------------------------------------------

    def save_grades(self, sid: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._load(sid)
            if "general_feedback" in payload:
                if not isinstance(payload["general_feedback"], str):
                    raise StorageError("general_feedback must be a string")
                data["general_feedback"] = payload["general_feedback"]
            if "grades" in payload:
                grades = payload["grades"]
                if not isinstance(grades, dict):
                    raise StorageError("grades must be an object")
                data["grades"] = {str(t): _clean_entry(e) for t, e in grades.items()}
            if "overrides" in payload:
                overrides = payload["overrides"]
                if not isinstance(overrides, dict):
                    raise StorageError("overrides must be an object")
                cleaned: dict[str, Any] = {}
                for student, tasks in overrides.items():
                    if str(student) not in data["students"]:
                        raise StorageError(f"Override for non-member: {student}")
                    if not isinstance(tasks, dict):
                        raise StorageError("override must be an object")
                    entries = {str(t): _clean_entry(e) for t, e in tasks.items()}
                    entries = {
                        t: e for t, e in entries.items() if e["points"] is not None or e["feedback"]
                    }
                    if entries:
                        cleaned[str(student)] = entries
                data["overrides"] = cleaned
            self._save(data)
            return self._load(sid)
