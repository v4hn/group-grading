"use strict";

const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  el.append(...children.flat().filter((c) => c != null && c !== false));
  return el;
}

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* non-JSON error body */ }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return (res.headers.get("content-type") || "").includes("json") ? res.json() : res.text();
}

let statusTimer;
function setStatus(msg) {
  const el = $("#status");
  el.textContent = msg;
  clearTimeout(statusTimer);
  if (msg) statusTimer = setTimeout(() => (el.textContent = ""), 6000);
}

const guard = (fn) => async (...args) => {
  try { await fn(...args); } catch (e) { setStatus(e.message); }
};

const S = { students: [], studentById: {}, tasks: {}, submissions: [] };
const fullName = (s) => `${s.first_name} ${s.name}`.trim();
const nameOf = (id) => (S.studentById[id] ? fullName(S.studentById[id]) : id);
const fileUrl = (sid, name) => `/api/submissions/${encodeURIComponent(sid)}/files/${encodeURIComponent(name)}`;
const renderMd = (text) => DOMPurify.sanitize(marked.parse(text || ""));

async function loadSubmissions() {
  S.submissions = await api("GET", "/api/submissions");
}

// ---------------------------------------------------------------- tabs

function showTab(name) {
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("active", b.dataset.tab === name);
  for (const t of document.querySelectorAll(".tab")) t.hidden = t.id !== `tab-${name}`;
  if (name === "submissions") renderSubmissionsTab();
  if (name === "grading") guard(renderGradingTab)();
  if (name === "overview") guard(loadOverview)();
}

document.querySelectorAll("#tabs button").forEach((b) =>
  b.addEventListener("click", guard(async () => {
    await flushSave();
    showTab(b.dataset.tab);
  }))
);

// Dropping outside a zone must not navigate away from the page.
for (const ev of ["dragover", "drop"]) window.addEventListener(ev, (e) => e.preventDefault());

// ---------------------------------------------------------------- submissions tab

const emptyForm = (assignment = Object.keys(S.tasks)[0] || "") => ({ id: null, assignment, group: [], pending: [], existing: [] });
let F = emptyForm();
let studentSort = null;

function renderSubmissionsTab() {
  renderForm();
  renderSubmissionTable();
}

function otherSubmissionFor(studentId) {
  return S.submissions.find(
    (s) => s.id !== F.id && s.assignment === F.assignment && s.students.includes(studentId)
  );
}

function suggestedMembers() {
  const selected = new Set(F.group);
  const out = new Set();
  for (const s of S.submissions) {
    if (s.id === F.id || !s.students.some((id) => selected.has(id))) continue;
    for (const id of s.students) if (!selected.has(id) && !otherSubmissionFor(id)) out.add(id);
  }
  return [...out];
}

function renderForm() {
  $("#form-title").textContent = F.id ? `Edit ${F.id}` : "New submission";

  const sel = $("#assignment");
  sel.replaceChildren(...Object.keys(S.tasks).map((a) => h("option", { value: a, selected: a === F.assignment }, a)));

  const zone = $("#group-zone");
  zone.replaceChildren(
    ...(F.group.length
      ? F.group.map((id) =>
          h("span", { class: "chip" }, nameOf(id), h("button", {
            title: "Remove", onclick: () => { F.group = F.group.filter((g) => g !== id); renderForm(); },
          }, "×"))
        )
      : [h("span", { class: "placeholder" }, "Drop students here")]),
    ...suggestedMembers().map((id) =>
      h("span", { class: "chip suggested", title: "Suggested: has worked with a selected member. Click to add.", onclick: () => addToGroup(id) }, nameOf(id)))
  );

  const dupes = F.group
    .map((id) => [id, otherSubmissionFor(id)])
    .filter(([, s]) => s)
    .map(([id, s]) => `${nameOf(id)} is already in ${s.id}`);
  $("#group-warning").textContent = dupes.join("; ");

  const list = $("#file-list");
  list.replaceChildren(
    ...F.existing.map((name) =>
      h("li", {}, h("a", { href: fileUrl(F.id, name), onclick: (e) => e.stopPropagation() }, name),
        h("button", { class: "danger", onclick: guard(async (e) => {
          e.stopPropagation();
          if (!confirm(`Delete ${name} from ${F.id}?`)) return;
          const sub = await api("DELETE", fileUrl(F.id, name));
          F.existing = sub.files;
          await loadSubmissions();
          renderSubmissionsTab();
        }) }, "×"))
    ),
    ...F.pending.map((f, i) =>
      h("li", {}, h("span", { class: "tag new" }, "new"), f.name,
        h("button", { onclick: (e) => { e.stopPropagation(); F.pending.splice(i, 1); renderForm(); } }, "×"))
    )
  );
  $("#file-zone .placeholder").hidden = F.existing.length + F.pending.length > 0;

  renderStudentList();
}

function renderStudentList() {
  const q = $("#student-search").value.trim().toLowerCase();
  for (const b of document.querySelectorAll("#student-sort button")) b.classList.toggle("active", b.dataset.sort === studentSort);
  const items = S.students
    .filter((s) => !q || `${fullName(s)} ${s.name} ${s.id}`.toLowerCase().includes(q))
    .sort((a, b) => studentSort ? a[studentSort].localeCompare(b[studentSort], undefined, { numeric: true, sensitivity: "base" }) : 0)
    .map((s) => {
      const used = F.group.includes(s.id);
      const other = otherSubmissionFor(s.id);
      const li = h("li", { draggable: used ? false : "true", class: [used && "used", other && "assigned"].filter(Boolean).join(" "), title: other ? `Already in ${other.id}` : "" },
        h("span", {}, `${s.name}, ${s.first_name}`),
        h("span", { class: "meta" }, s.id));
      li.addEventListener("dragstart", (e) => e.dataTransfer.setData("text/x-student-id", s.id));
      li.addEventListener("dblclick", () => addToGroup(s.id));
      return li;
    });
  $("#student-count").textContent = items.length;
  $("#student-list").replaceChildren(...items);
}

function addToGroup(id) {
  if (F.group.includes(id)) return;
  F.group.push(id);
  renderForm();
}

function dropHandlers(zone, onDrop) {
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); onDrop(e.dataTransfer); });
}

dropHandlers($("#group-zone"), (dt) => {
  const id = dt.getData("text/x-student-id");
  if (id) addToGroup(id);
});

function addFiles(files) {
  for (const f of files) {
    if (!F.pending.some((p) => p.name === f.name && p.size === f.size)) F.pending.push(f);
  }
  renderForm();
}

dropHandlers($("#file-zone"), (dt) => {
  const files = [];
  let skipped = 0;
  for (const item of dt.items) {
    if (item.kind !== "file") continue;
    if (item.webkitGetAsEntry?.()?.isDirectory) { skipped++; continue; }
    const f = item.getAsFile();
    if (f) files.push(f);
  }
  if (skipped) setStatus("Folders are not supported; drop individual files");
  addFiles(files);
});
$("#file-zone").addEventListener("click", () => $("#file-input").click());
$("#file-zone").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#file-input").click(); });
$("#file-input").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });

$("#student-search").addEventListener("input", renderStudentList);
$("#student-sort").addEventListener("click", (e) => {
  if (!e.target.dataset.sort) return;
  studentSort = e.target.dataset.sort;
  renderStudentList();
});
$("#assignment").addEventListener("change", (e) => { F.assignment = e.target.value; renderForm(); });
$("#reset-form").addEventListener("click", () => { F = emptyForm(); renderForm(); });

$("#save-submission").addEventListener("click", guard(async () => {
  if (!F.group.length) throw new Error("Add at least one student to the group");
  const body = { assignment: F.assignment, students: F.group };
  let sub;
  if (F.id) sub = await api("PUT", `/api/submissions/${encodeURIComponent(F.id)}`, body);
  else sub = await api("POST", "/api/submissions", body);
  F.id = sub.id;
  if (F.pending.length) {
    const fd = new FormData();
    for (const f of F.pending) fd.append("files", f, f.name);
    await api("POST", `/api/submissions/${encodeURIComponent(sub.id)}/files`, fd);
  }
  await loadSubmissions();
  setStatus(`Saved ${sub.id}`);
  F = emptyForm(sub.assignment);
  renderSubmissionsTab();
}));

function renderSubmissionTable() {
  const head = h("tr", {}, ...["ID", "Assignment", "Members", "Files", ""].map((t) => h("th", {}, t)));
  const rows = [...S.submissions].reverse().map((s) =>
    h("tr", {},
      h("td", {}, s.id),
      h("td", {}, s.assignment),
      h("td", {}, s.students.map(nameOf).join(", ")),
      h("td", {}, ...s.files.flatMap((f, i) => [i ? ", " : null, h("a", { href: fileUrl(s.id, f) }, f)])),
      h("td", {},
        h("button", { onclick: guard(() => openEditing(s)) }, "Edit"), " ",
        h("button", { onclick: guard(async () => { await openGrading(s.id); }) }, "Grade"), " ",
        h("button", { class: "danger", onclick: guard(async () => {
          if (!confirm(`Delete ${s.id} including its files and grades?`)) return;
          await api("DELETE", `/api/submissions/${encodeURIComponent(s.id)}`);
          if (F.id === s.id) F = emptyForm();
          await loadSubmissions();
          renderSubmissionsTab();
        }) }, "Delete")))
  );
  $("#submission-table").replaceChildren(head, ...rows);
}

// ---------------------------------------------------------------- grading tab

const G = { sub: null, timer: null, dirty: false, editors: [], previews: [], overrideStudent: null };

async function flushSave() {
  clearTimeout(G.timer);
  G.timer = null;
  await saveGrades();
}

async function saveGrades() {
  if (!G.dirty || !G.sub) return;
  const sub = G.sub;
  G.dirty = false;
  $("#save-state").textContent = "Saving…";
  try {
    await api("PUT", `/api/submissions/${encodeURIComponent(sub.id)}/grades`, {
      general_feedback: sub.general_feedback,
      grades: sub.grades,
      overrides: sub.overrides,
    });
    $("#save-state").textContent = "Saved";
  } catch (e) {
    G.dirty = true;
    $("#save-state").textContent = "Save failed";
    setStatus(e.message);
  }
}

function scheduleSave() {
  G.dirty = true;
  $("#save-state").textContent = "Unsaved changes…";
  clearTimeout(G.timer);
  G.timer = setTimeout(guard(saveGrades), 600);
}

window.addEventListener("beforeunload", (e) => { if (G.dirty) e.preventDefault(); });

function mdEditor(value, onChange) {
  const host = h("div");
  const preview = h("div", { class: "preview" });
  const wrap = h("div", { class: "md-wrap" }, host, preview);
  const cm = CodeMirror(host, { value: value || "", mode: "markdown", lineWrapping: true, viewportMargin: Infinity });
  const update = () => {
    preview.innerHTML = renderMd(cm.getValue());
    cm.refresh();
  };
  cm.on("change", () => { onChange(cm.getValue()); update(); });
  G.editors.push(cm);
  G.previews.push(update);
  return wrap;
}

function pointsInput(value, max, onChange) {
  const input = h("input", { type: "number", min: "0", step: "any", value: value ?? "" });
  const check = () => input.classList.toggle("over-max", input.value !== "" && Number(input.value) > max);
  input.addEventListener("input", () => {
    check();
    onChange(input.value === "" ? null : Number(input.value));
  });
  input.addEventListener("wheel", (e) => {
    e.preventDefault();
    const next = (Number(input.value) || 0) + (e.deltaY < 0 ? 1 : -1);
    input.value = String(Math.min(max, Math.max(0, Math.round(next * 1e6) / 1e6)));
    input.dispatchEvent(new Event("input"));
  });
  check();
  return input;
}

async function renderGradingTab() {
  const sel = $("#grade-submission");
  const current = G.sub ? G.sub.id : sel.value;
  sel.replaceChildren(
    ...S.submissions.map((s) => h("option", { value: s.id, selected: s.id === current }, `${s.id} – ${s.students.map(nameOf).join(", ")}`))
  );
  if (!S.submissions.length) {
    G.sub = null;
    $("#grading-body").replaceChildren(h("p", {}, "No submissions yet."));
    return;
  }
  await loadGrade(sel.value);
}

async function openGrading(sid) {
  await flushSave();
  G.sub = { id: sid };
  showTab("grading");
}

async function openEditing(s) {
  await flushSave();
  F = { id: s.id, assignment: s.assignment, group: [...s.students], pending: [], existing: [...s.files] };
  showTab("submissions");
  window.scrollTo(0, 0);
}

async function loadGrade(sid) {
  const sub = await api("GET", `/api/submissions/${encodeURIComponent(sid)}`);
  G.sub = sub;
  G.overrideStudent = sub.students[0];
  $("#save-state").textContent = "";
  renderGradingBody();
}

function renderGradingBody() {
  const sub = G.sub;
  const tasks = S.tasks[sub.assignment] || {};
  G.editors = [];
  G.previews = [];
  const body = $("#grading-body");

  const header = h("div", { class: "panel", style: "margin-bottom:12px" },
    h("button", { style: "float:right", onclick: guard(() => openEditing(sub)) }, "Edit submission"),
    h("strong", {}, sub.assignment), " · ", sub.students.map(nameOf).join(", "),
    h("div", { class: "hint" }, "Files: ", ...(sub.files.length
      ? sub.files.flatMap((f, i) => [i ? ", " : null, h("a", { href: fileUrl(sub.id, f) }, f)])
      : ["none"])));

  const cards = Object.entries(tasks).map(([task, max]) => {
    const entry = (sub.grades[task] ||= { points: null, feedback: "" });
    return h("div", { class: "task-card" },
      h("div", { class: "task-head" }, h("h3", {}, task),
        pointsInput(entry.points, max, (v) => { entry.points = v; scheduleSave(); }),
        `/ ${max}`),
      mdEditor(entry.feedback, (v) => { entry.feedback = v; scheduleSave(); }));
  });

  const general = h("div", { class: "task-card" }, h("h3", {}, "General feedback"),
    mdEditor(sub.general_feedback, (v) => { sub.general_feedback = v; scheduleSave(); }));

  const overrideHost = h("div");
  const memberSelect = h("select", { onchange: (e) => { G.overrideStudent = e.target.value; renderOverrides(); } },
    ...sub.students.map((id) => h("option", { value: id, selected: id === G.overrideStudent }, nameOf(id))));
  const renderOverrides = () => {
    const sid = G.overrideStudent;
    overrideHost.replaceChildren(...Object.entries(tasks).map(([task, max]) => {
      const entry = ((sub.overrides[sid] ||= {})[task] ||= { points: null, feedback: "" });
      return h("div", { class: "task-card override-box" },
        h("div", { class: "task-head" }, h("h3", {}, task),
          pointsInput(entry.points, max, (v) => { entry.points = v; scheduleSave(); }), `/ ${max}`),
        mdEditor(entry.feedback, (v) => { entry.feedback = v; scheduleSave(); }));
    }));
    for (const cm of G.editors) cm.refresh();
  };
  const overrides = h("div", { class: "panel" }, h("h2", {}, "Individual overrides"),
    h("p", { class: "hint" }, "Empty fields fall back to the group value. Overriding feedback replaces the group feedback for this student."),
    h("label", {}, "Student ", memberSelect), overrideHost);

  const showGeneral = Object.keys(tasks).length > 1;
  const showOverrides = sub.students.length > 1;
  body.replaceChildren(header, ...cards, ...(showGeneral ? [general] : []), ...(showOverrides ? [overrides] : []));
  if (showOverrides) renderOverrides();
  G.previews.forEach((u) => u());
}

$("#grade-submission").addEventListener("change", guard(async (e) => {
  await flushSave();
  await loadGrade(e.target.value);
}));

// ---------------------------------------------------------------- overview tab

const O = { data: null, sortKey: "name", sortDir: 1 };

async function loadOverview() {
  O.data = await api("GET", "/api/overview");
  renderOverview();
}

function sortValue(row, key) {
  if (key === "id") return row.student.id;
  if (key === "name") return row.student.name.toLowerCase();
  if (key === "first_name") return row.student.first_name.toLowerCase();
  if (key === "total") return row.total;
  if (key === "percent") return row.percent;
  return row.assignments[key.slice(2)]?.points ?? null;
}

// Graded values first, then ungraded, then not submitted; independent of sort direction.
function sortRank(row, key) {
  if (!key.startsWith("a:")) return sortValue(row, key) === null ? 1 : 0;
  const cell = row.assignments[key.slice(2)];
  return !cell ? 2 : cell.points === null ? 1 : 0;
}

function renderOverview() {
  const { assignments, rows } = O.data;
  const q = $("#overview-filter").value.trim().toLowerCase();
  const visible = rows
    .filter((r) => !q || `${r.student.name} ${r.student.first_name} ${r.student.id}`.toLowerCase().includes(q))
    .sort((a, b) => {
      const rx = sortRank(a, O.sortKey), ry = sortRank(b, O.sortKey);
      if (rx !== ry) return rx - ry;
      const x = sortValue(a, O.sortKey), y = sortValue(b, O.sortKey);
      if (x === null) return 0;
      return (x < y ? -1 : x > y ? 1 : 0) * O.sortDir;
    });

  const th = (label, key) => h("th", { class: "sortable", onclick: () => {
    O.sortDir = O.sortKey === key ? -O.sortDir : 1;
    O.sortKey = key;
    renderOverview();
  } }, label, O.sortKey === key ? (O.sortDir > 0 ? " ▲" : " ▼") : "");

  const head = h("tr", {},
    th("ID", "id"), th("Name", "name"), th("First Name", "first_name"),
    ...assignments.map((a) => th(`${a.name} (/${a.max})`, `a:${a.name}`)),
    th("Total", "total"), th("%", "percent"), h("th", {}, ""));

  const body = visible.map((r) => {
    const cells = assignments.map((a) => {
      const c = r.assignments[a.name];
      if (!c) return h("td", { class: "missing" }, "–");
      const label = c.points === null ? "ungraded" : `${c.points} / ${c.max}`;
      const warn = c.duplicates.length ? ` ⚠ also in ${c.duplicates.join(", ")}` : "";
      return h("td", { class: "num", title: c.submission_id + warn },
        h("button", { class: "link", onclick: guard(() => openGrading(c.submission_id)) }, label),
        c.duplicates.length ? " ⚠" : "");
    });
    const sid = encodeURIComponent(r.student.id);
    return h("tr", {},
      h("td", {}, r.student.id), h("td", {}, r.student.name), h("td", {}, r.student.first_name), ...cells,
      h("td", { class: "num", title: "Sum over graded assignments" }, r.max ? `${r.total} / ${r.max}` : "–"),
      h("td", { class: "num" }, r.percent === null ? "–" : `${r.percent}%`),
      h("td", {},
        h("button", { onclick: guard(() => openReport(r.student)) }, "Report"), " ",
        h("a", { class: "button", href: `/api/students/${sid}/bundle.zip` }, "ZIP")));
  });
  $("#overview-table").replaceChildren(head, ...body);
}

$("#overview-filter").addEventListener("input", () => O.data && renderOverview());
$("#export-csv").addEventListener("click", () => { location.href = "/api/overview.csv"; });
$("#download-all").addEventListener("click", () => { location.href = "/api/bundle-all.zip"; });

async function openReport(student) {
  const sid = encodeURIComponent(student.id);
  const text = await api("GET", `/api/students/${sid}/report.md`);
  $("#report-title").textContent = `Report: ${fullName(student)} (${student.id})`;
  $("#report-text").value = text;
  $("#report-preview").innerHTML = renderMd(text);
  $("#report-download").href = `/api/students/${sid}/report.md?download=true`;
  $("#report-dialog").showModal();
}

$("#report-close").addEventListener("click", () => $("#report-dialog").close());
$("#report-copy").addEventListener("click", guard(async () => {
  await navigator.clipboard.writeText($("#report-text").value);
  $("#report-copy").textContent = "Copied";
  setTimeout(() => ($("#report-copy").textContent = "Copy Markdown"), 1500);
}));

// ---------------------------------------------------------------- init

guard(async () => {
  [S.students, S.tasks] = await Promise.all([api("GET", "/api/students"), api("GET", "/api/tasks")]);
  S.studentById = Object.fromEntries(S.students.map((s) => [s.id, s]));
  await loadSubmissions();
  F = emptyForm();
  renderSubmissionsTab();
})();
