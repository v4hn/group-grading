"""FastAPI application."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import reports, scoring
from .storage import Course, NotFound, StorageError

STATIC_DIR = Path(__file__).parent / "static"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class SubmissionCreate(BaseModel):
    assignment: str
    students: list[str]


class SubmissionUpdate(BaseModel):
    assignment: str | None = None
    students: list[str] | None = None


def create_app(course_dir: str | os.PathLike[str]) -> FastAPI:
    course = Course(course_dir)
    app = FastAPI(title="Group Grading")

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Guards against DNS rebinding and cross-site writes to the local server.
        hostname = urlsplit("//" + request.headers.get("host", "")).hostname
        if hostname not in LOCAL_HOSTS:
            return PlainTextResponse("Forbidden host", status_code=403)
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD") and origin:
            if urlsplit(origin).netloc != request.headers.get("host"):
                return PlainTextResponse("Forbidden origin", status_code=403)
        return await call_next(request)

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(StorageError)
    async def _bad_request(_: Request, exc: StorageError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/api/students")
    def students():
        return course.students()

    @app.get("/api/tasks")
    def tasks():
        return course.tasks()

    @app.get("/api/submissions")
    def list_submissions():
        return course.list_submissions()

    @app.post("/api/submissions", status_code=201)
    def create_submission(body: SubmissionCreate):
        return course.create_submission(body.assignment, body.students)

    @app.get("/api/submissions/{sid}")
    def get_submission(sid: str):
        return course.get_submission(sid)

    @app.put("/api/submissions/{sid}")
    def update_submission(sid: str, body: SubmissionUpdate):
        return course.update_submission(sid, body.assignment, body.students)

    @app.delete("/api/submissions/{sid}", status_code=204)
    def delete_submission(sid: str):
        course.delete_submission(sid)

    @app.post("/api/submissions/{sid}/files")
    def upload_files(sid: str, files: list[UploadFile] = File(...)):
        for f in files:
            course.add_file(sid, f.filename or "", f.file)
        return course.get_submission(sid)

    @app.get("/api/submissions/{sid}/files/{name}")
    def download_file(sid: str, name: str):
        return FileResponse(course.file_path(sid, name), filename=name)

    @app.delete("/api/submissions/{sid}/files/{name}")
    def delete_file(sid: str, name: str):
        course.delete_file(sid, name)
        return course.get_submission(sid)

    @app.put("/api/submissions/{sid}/grades")
    def save_grades(sid: str, body: dict[str, Any]):
        return course.save_grades(sid, body)

    @app.get("/api/overview")
    def overview():
        return scoring.overview(course)

    @app.get("/api/overview.csv")
    def overview_csv():
        text = reports.overview_csv(scoring.overview(course))
        return Response(
            text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="overview.csv"'},
        )

    @app.get("/api/students/{student_id}/results")
    def student_results(student_id: str):
        if student_id not in course.student_map():
            raise NotFound("Unknown student")
        return scoring.student_results(course, student_id)

    @app.get("/api/students/{student_id}/report.md")
    def student_report(student_id: str, download: bool = False):
        text = reports.student_report(course, student_id)
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{student_id}.md"'
        return Response(text, media_type="text/markdown; charset=utf-8", headers=headers)

    @app.get("/api/submissions/{sid}/report.md")
    def submission_report(sid: str, student: str, download: bool = False):
        text = reports.student_report(course, student, sid)
        headers = {}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{student}_{sid}.md"'
        return Response(text, media_type="text/markdown; charset=utf-8", headers=headers)

    @app.get("/api/students/{student_id}/bundle.zip")
    def student_bundle(student_id: str):
        path, filename = reports.student_zip(course, student_id)
        return FileResponse(
            path, filename=filename, media_type="application/zip",
            background=BackgroundTask(os.unlink, path),
        )

    @app.get("/api/bundle-all.zip")
    def bundle_all():
        path = reports.all_students_zip(course)
        return FileResponse(
            path, filename="all-students.zip", media_type="application/zip",
            background=BackgroundTask(os.unlink, path),
        )

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
