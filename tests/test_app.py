import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from group_grading.main import create_app
from group_grading.storage import Course, StorageError, sanitize_filename

STUDENTS = "Name;First Name;ID\nMüller;Anna;1\nSchmidt;Ben;2\nWeber;Clara;3\nFischer;David;4\nWagner;Eva;5\nKoch;Hans;6\n"
TASKS = "a1:\n  T1: 10\n  T2: 5\na2:\n  X: 20\n"


@pytest.fixture
def course_dir(tmp_path):
    (tmp_path / "students.csv").write_text(STUDENTS, encoding="utf-8-sig")
    (tmp_path / "tasks.yaml").write_text(TASKS, encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(course_dir):
    return TestClient(create_app(course_dir), base_url="http://localhost")


def make_sub(client, assignment="a1", students=("1", "2")):
    r = client.post("/api/submissions", json={"assignment": assignment, "students": list(students)})
    assert r.status_code == 201, r.text
    return r.json()


def test_students_parsed_with_bom_and_semicolon(client):
    students = client.get("/api/students").json()
    assert len(students) == 6
    assert students[0] == {"id": "1", "name": "Müller", "first_name": "Anna"}


def test_tasks_keep_order(client):
    assert list(client.get("/api/tasks").json()["a1"]) == ["T1", "T2"]


def test_task_weights(client, course_dir):
    (course_dir / "tasks.yaml").write_text("a1:\n  T1: 10\n  T2:\n    Points: 5\n    Weight: 3\n", encoding="utf-8")
    assert client.get("/api/tasks").json()["a1"] == {"T1": 10, "T2": 5}
    sub = make_sub(client)
    client.put(f"/api/submissions/{sub['id']}/grades", json={"grades": {"T1": {"points": 10}, "T2": {"points": 4}}})
    result = client.get("/api/students/1/results").json()[0]
    assert (result["total"], result["max"]) == (22, 25)


def test_task_weight_invalid(client, course_dir):
    (course_dir / "tasks.yaml").write_text("a1:\n  T1:\n    Points: 5\n    Weigth: 3\n", encoding="utf-8")
    assert client.get("/api/tasks").status_code == 400


def test_create_validation(client):
    bad = [
        {"assignment": "nope", "students": ["1"]},
        {"assignment": "a1", "students": []},
        {"assignment": "a1", "students": ["1", "1"]},
        {"assignment": "a1", "students": ["999"]},
    ]
    for body in bad:
        assert client.post("/api/submissions", json=body).status_code == 400, body


def test_ids_increment(client):
    assert make_sub(client)["id"] == "a1-001"
    assert make_sub(client, students=("3",))["id"] == "a1-002"


def test_update_group_drops_stale_overrides(client):
    sub = make_sub(client)
    client.put(f"/api/submissions/{sub['id']}/grades", json={"overrides": {"2": {"T1": {"points": 1}}}})
    r = client.put(f"/api/submissions/{sub['id']}", json={"students": ["1", "3"]})
    assert r.json()["overrides"] == {}


def test_upload_collisions_and_traversal(client, course_dir):
    sub = make_sub(client)
    url = f"/api/submissions/{sub['id']}/files"
    files = [("files", ("../../evil.txt", b"x")), ("files", ("a.pdf", b"1")), ("files", ("a.pdf", b"2"))]
    r = client.post(url, files=files)
    assert r.status_code == 200
    assert r.json()["files"] == ["a (2).pdf", "a.pdf", "evil.txt"]
    assert not (course_dir.parent / "evil.txt").exists()
    assert client.get(f"{url}/a.pdf").content == b"1"
    assert client.get(f"{url}/..%2F..%2Fstudents.csv").status_code == 404


def test_unknown_submission_ids(client):
    assert client.get("/api/submissions/..").status_code in (404, 400)
    assert client.get("/api/submissions/nothing").status_code == 404


def test_grade_validation(client):
    sub = make_sub(client)
    url = f"/api/submissions/{sub['id']}/grades"
    assert client.put(url, json={"grades": {"T1": {"points": -1}}}).status_code == 400
    assert client.put(url, json={"grades": {"T1": {"points": "x"}}}).status_code == 400
    assert client.put(url, json={"overrides": {"3": {"T1": {"points": 1}}}}).status_code == 400


def grade(client, sid):
    r = client.put(
        f"/api/submissions/{sid}/grades",
        json={
            "general_feedback": "Well done.",
            "grades": {"T1": {"points": 8, "feedback": "ok"}, "T2": {"points": 5, "feedback": ""}},
            "overrides": {"2": {"T1": {"points": 6, "feedback": "late"}}},
        },
    )
    assert r.status_code == 200, r.text


def test_overview_uses_overrides(client):
    sub = make_sub(client)
    grade(client, sub["id"])
    rows = {r["student"]["id"]: r for r in client.get("/api/overview").json()["rows"]}
    assert rows["1"]["assignments"]["a1"]["points"] == 13
    assert rows["2"]["assignments"]["a1"]["points"] == 11
    assert rows["2"]["percent"] == pytest.approx(73.3)
    assert rows["3"]["assignments"] == {} and rows["3"]["percent"] is None


def test_ungraded_submission_has_no_points(client):
    make_sub(client)
    row = next(r for r in client.get("/api/overview").json()["rows"] if r["student"]["id"] == "1")
    assert row["assignments"]["a1"]["points"] is None and row["max"] == 0


def test_duplicate_assignment_latest_wins(client):
    first = make_sub(client, students=("1",))
    second = make_sub(client, students=("1",))
    client.put(f"/api/submissions/{second['id']}/grades", json={"grades": {"T1": {"points": 3}}})
    cell = next(r for r in client.get("/api/overview").json()["rows"] if r["student"]["id"] == "1")["assignments"]["a1"]
    assert cell["submission_id"] == second["id"] and cell["duplicates"] == [first["id"]]


def test_report_and_csv(client):
    sub = make_sub(client)
    grade(client, sub["id"])
    report = client.get("/api/students/2/report.md").text
    assert "Ben Schmidt" in report and "| T1 | 6 / 10 |" in report
    assert "late" in report and "Well done." in report and "**Total: 11 / 15 points" in report
    csv_text = client.get("/api/overview.csv").text.splitlines()
    assert csv_text[0] == "ID,Name,First Name,a1,a2,Total,Max,Percent"
    assert csv_text[2].startswith("2,Schmidt,Ben,11,,11,15,")
    assert client.get("/api/students/999/report.md").status_code == 404


def test_zip_bundles(client):
    sub = make_sub(client)
    client.post(f"/api/submissions/{sub['id']}/files", files=[("files", ("sol.txt", b"hi"))])
    r = client.get("/api/students/1/bundle.zip")
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert sorted(names) == ["a1/sol.txt", "report.md"]
    names = zipfile.ZipFile(io.BytesIO(client.get("/api/bundle-all.zip").content)).namelist()
    assert "1_Anna_Müller/a1/sol.txt" in names and "2_Ben_Schmidt/report.md" in names
    assert not any(n.startswith("3_") for n in names)


def test_host_and_origin_checks(course_dir):
    app = create_app(course_dir)
    assert TestClient(app, base_url="http://evil.example").get("/api/students").status_code == 403
    c = TestClient(app, base_url="http://localhost")
    r = c.post("/api/submissions", json={"assignment": "a1", "students": ["1"]}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_sanitize_filename():
    assert sanitize_filename("C:\\dir\\file.txt") == "file.txt"
    assert sanitize_filename(".hidden") == "hidden"
    with pytest.raises(StorageError):
        sanitize_filename("..")


def test_course_reload(course_dir):
    c = Course(course_dir)
    sub = c.create_submission("a1", ["1"])
    assert Course(course_dir).get_submission(sub["id"])["students"] == ["1"]
