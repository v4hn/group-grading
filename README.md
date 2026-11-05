# Group Grading

Local web app to collect group submissions, grade tasks with Markdown feedback, and export per-student reports and file bundles. Data is stored as plain files in a course folder.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install .            # or: pip install -e '.[dev]' for development
.venv/bin/group-grading ./course
```

Open http://127.0.0.1:8000. The server binds to localhost only.

## Course folder

```
course/
  students.csv        # columns: Name, First Name, ID (comma, semicolon or tab separated)
  tasks.yaml          # assignment -> task -> max points
  submissions/
    assignment1-001/
      submission.yaml # group, grades, overrides, feedback
      files/          # uploaded files
```

`tasks.yaml` is re-read on every request:

```yaml
assignment1:
  Task 1: 10
  Task 2:
    Points: 15
    Weight: 2   # optional, default 1
```

The weight multiplies a task's points in the assignment total and maximum (the per-task grade stays unweighted).

## Workflow

1. **Submissions**: pick the assignment, drag students into the group (or double-click), drop files, save.
2. **Grading**: enter points and Markdown feedback per task; changes autosave. Use "Individual overrides" to deviate for one student. Points above the task maximum are allowed (bonus) but highlighted.
3. **Overview**: sortable points table, per-student Markdown report and ZIP, CSV export, ZIP of all students.

If a student has several submissions for one assignment, the latest counts and the cell is marked with a warning. Overview totals and percentages only cover graded assignments.

## AI disclaimer

This project contains entirely "slopped code" (GitHub Copilot, Claude Sonnet 5.5).
