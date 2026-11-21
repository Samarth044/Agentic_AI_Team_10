import { useState } from "react";
import { api, fileToBase64 } from "../../api";
import { AgentWorking } from "../../components/Common";
import { Alert, Button, Card, Chips, Field, Mode, usePoll } from "../../ui";

export default function Profile({ me, refresh }) {
  const s = me.student;
  const working = ["parsing", "matching", "queued"].includes(s.agent_status);
  usePoll(refresh, working, 2000);
  return (
    <>
      <div className="page-head"><div><h1>Profile & resume</h1><div className="muted">Agents use this to match you and check eligibility.</div></div></div>
      <AgentWorking status={s.agent_status} message={s.agent_message} />
      <div className="split">
        <div>
          <ResumeCard s={s} refresh={refresh} />
          {s.resume_profile && <ParsedResume s={s} refresh={refresh} />}
        </div>
        <Details s={s} refresh={refresh} />
      </div>
    </>
  );
}

function ResumeCard({ s, refresh }) {
  const [err, setErr] = useState("");
  const [over, setOver] = useState(false);
  const upload = async (file) => {
    setErr("");
    if (!file) return;
    if (!/\.(pdf|docx|txt)$/i.test(file.name)) return setErr("Upload a PDF, DOCX or TXT file");
    try {
      await api.post("/profile/resume", { filename: file.name, content_base64: await fileToBase64(file) });
      refresh();
    } catch (e) { setErr(e.message); }
  };
  return (
    <Card title="Resume" subtitle={s.resume_filename ? `Current file: ${s.resume_filename}` : "PDF, DOCX or TXT, up to 5 MB"}>
      <Alert>{err}</Alert>
      <label className={`dropzone ${over ? "over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files[0]); }}>
        <input type="file" accept=".pdf,.docx,.txt" hidden onChange={(e) => upload(e.target.files[0])} />
        <div style={{ fontSize: 26 }}>⇪</div>
        <b>{s.resume_filename ? "Upload a new version" : "Drop your resume here or click to choose"}</b>
        <div className="small muted">The Resume Agent extracts your skills and projects; your name, email and phone are hidden from the AI.</div>
      </label>
    </Card>
  );
}

const txt = (v) => (v && typeof v === "object" ? Object.values(v).filter(Boolean).join(" · ") : String(v ?? ""));

function ParsedResume({ s, refresh }) {
  const p = s.resume_profile;
  const [skills, setSkills] = useState(s.skills || []);
  const [add, setAdd] = useState("");
  const dirty = JSON.stringify(skills) !== JSON.stringify(s.skills || []);
  const save = async () => { await api.put("/profile/skills", { skills }); refresh(); };
  const evidence = Object.fromEntries((p.skills || []).map((x) => [x.name, x]));
  return (
    <Card title="What the Resume Agent found" actions={<Mode mode={p.mode} />}>
      <p><b>{p.headline}</b></p>
      <p>{p.summary}</p>
      <h4 className="mt2">Skills <span className="small muted">(click a skill to remove it, or add missing ones)</span></h4>
      <div className="chips mt">
        {skills.map((k) => (
          <span key={k} className="chip removable" title={evidence[k]?.evidence ? `${evidence[k].level || ""}: ${evidence[k].evidence}` : "added by you"}
            onClick={() => setSkills(skills.filter((x) => x !== k))}>{k} ×</span>
        ))}
      </div>
      <form className="row mt" onSubmit={(e) => { e.preventDefault(); const v = add.trim().toLowerCase(); if (v && !skills.includes(v)) setSkills([...skills, v]); setAdd(""); }}>
        <input value={add} onChange={(e) => setAdd(e.target.value)} placeholder="Add a skill, e.g. docker" style={{ width: 240 }} />
        <button className="btn">Add</button>
        {dirty && <Button kind="primary" onClick={save}>Save skills & re-match</Button>}
      </form>
      {p.projects?.length > 0 && (<>
        <h4 className="mt2">Projects</h4>
        {p.projects.map((pr, i) => (
          <div key={i} className="mt"><b>{txt(pr.title)}</b><div className="small">{txt(pr.description)}</div><Chips items={(pr.skills || []).map(txt)} /></div>
        ))}
      </>)}
      <div className="grid2 mt2">
        {p.education?.length > 0 && <div><h4>Education</h4><ul className="small">{p.education.map((e, i) => <li key={i}>{typeof e === "object" ? [e.degree, e.institution, e.year, e.score].filter(Boolean).join(" · ") : txt(e)}</li>)}</ul></div>}
        {(p.certifications?.length > 0 || p.achievements?.length > 0) && <div><h4>Achievements</h4><ul className="small">{[...(p.certifications || []), ...(p.achievements || [])].slice(0, 6).map((a, i) => <li key={i}>{txt(a)}</li>)}</ul></div>}
      </div>
      {p.suggested_roles?.length > 0 && <div className="mt2"><h4>Roles that suit you</h4><Chips items={p.suggested_roles.map(txt)} /></div>}
      {p.resume_tips?.length > 0 && <Alert tone="info"><b>Resume tips:</b> {p.resume_tips.map(txt).join(" ")}</Alert>}
    </Card>
  );
}

function Details({ s, refresh }) {
  const [f, setF] = useState({ ...s, open_to_remote: !!s.open_to_remote });
  const [msg, setMsg] = useState(["", ""]);
  const bind = (k) => ({ value: f[k] ?? "", onChange: (e) => setF({ ...f, [k]: e.target.value }) });
  const save = async () => {
    setMsg(["", ""]);
    try {
      const keys = ["name", "usn", "phone", "department", "semester", "cgpa", "active_backlogs", "attendance_pct",
        "preferred_domains", "preferred_locations", "links"];
      await api.put("/profile", { ...Object.fromEntries(keys.map((k) => [k, f[k]])), open_to_remote: f.open_to_remote ? 1 : 0 });
      setMsg(["ok", "Saved. Agents are re-checking your matches."]);
      refresh();
    } catch (e) { setMsg(["error", e.message]); }
  };
  return (
    <Card title="Academic details & preferences">
      <div className="form">
        <Alert tone={msg[0]}>{msg[1]}</Alert>
        <Field label="Full name"><input {...bind("name")} /></Field>
        <div className="form-row">
          <Field label="USN"><input {...bind("usn")} /></Field>
          <Field label="Branch"><select {...bind("department")}>{["CSE", "AI", "ECE", "ME", "CE"].map((b) => <option key={b}>{b}</option>)}</select></Field>
        </div>
        <div className="form-row">
          <Field label="Semester"><input type="number" min="1" max="8" {...bind("semester")} /></Field>
          <Field label="CGPA"><input type="number" step="0.01" min="0" max="10" {...bind("cgpa")} /></Field>
        </div>
        <div className="form-row">
          <Field label="Active backlogs"><input type="number" min="0" {...bind("active_backlogs")} /></Field>
          <Field label="Attendance %"><input type="number" step="0.1" min="0" max="100" {...bind("attendance_pct")} /></Field>
        </div>
        <Field label="Phone"><input {...bind("phone")} /></Field>
        <Field label="Preferred domains" hint="Comma separated, e.g. AI/ML, Web development"><input {...bind("preferred_domains")} /></Field>
        <Field label="Preferred locations" hint="e.g. Bengaluru, Pune"><input {...bind("preferred_locations")} /></Field>
        <label className="check-row"><input type="checkbox" checked={f.open_to_remote} onChange={(e) => setF({ ...f, open_to_remote: e.target.checked })} /> Open to remote internships</label>
        <Field label="LinkedIn / GitHub"><input {...bind("links")} /></Field>
        <Button kind="primary" onClick={save}>Save details</Button>
      </div>
    </Card>
  );
}
