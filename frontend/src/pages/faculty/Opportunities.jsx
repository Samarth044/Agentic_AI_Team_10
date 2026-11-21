import { useState } from "react";
import { api } from "../../api";
import { Logo } from "../../components/Common";
import { Alert, Button, Card, Field, Mode, Modal, Tabs, fmtTime, useLoad } from "../../ui";

const BRANCHES = ["CSE", "AI", "ECE", "ME", "CE"];

export default function Opportunities({ me }) {
  const [d, reload] = useLoad(() => api.get("/opportunities"));
  const [tab, setTab] = useState("open");
  const [posting, setPosting] = useState(false);
  const [msg, setMsg] = useState("");
  if (!d) return <p>Loading…</p>;
  const rows = d.items.filter((o) => o.status === tab);
  const count = (s) => d.items.filter((o) => o.status === s).length;
  return (
    <>
      <div className="page-head">
        <div><h1>Internship postings</h1><div className="muted">Job boards last synced {d.boards_synced ? fmtTime(d.boards_synced) : "never"}</div></div>
        <div className="row">
          {me.permissions.includes("sync_boards") && <Button onClick={async () => { await api.post("/opportunities/sync"); setMsg("Syncing public job boards in the background. Students will be re-matched automatically."); }}>↻ Sync job boards</Button>}
          <button className="btn primary" onClick={() => setPosting(true)}>+ Post internship</button>
        </div>
      </div>
      <Alert tone="info">{msg}</Alert>
      <Tabs tabs={[["open", `Open (${count("open")})`], ["blocked", `Blocked by safety checks (${count("blocked")})`], ["closed", `Closed (${count("closed")})`]]} value={tab} onChange={setTab} />
      <Card>
        <table><tbody>{rows.map((o) => (
          <tr key={o.id}>
            <td style={{ width: 50 }}><Logo name={o.company} size={34} /></td>
            <td><b>{o.title}</b><div className="small muted">{o.company} · {o.location} · {o.stipend}</div>
              {o.flags.map((f) => <span key={f} className="flag">{f}</span>)}
              {tab === "blocked" && <div className="small muted mt">{o.description}</div>}</td>
            <td className="small">{["campus", "faculty"].includes(o.source) ? "College" : o.source}</td>
            <td className="small"><b>{o.matched_students}</b> eligible strong matches<div className="muted">{o.applications} applications</div></td>
            <td className="right">{o.url && <a className="small" href={o.url} target="_blank" rel="noreferrer">link ↗</a>}
              {tab === "open" && <div><Button kind="red" onClick={async () => { await api.post(`/opportunities/${o.id}/close`); reload(); }}>Close</Button></div>}</td>
          </tr>))}</tbody></table>
        {rows.length === 0 && <p className="muted">None.</p>}
      </Card>
      {posting && <PostModal onClose={() => setPosting(false)} onDone={(m) => { setPosting(false); setMsg(m); reload(); }} />}
    </>
  );
}

function PostModal({ onClose, onDone }) {
  const [text, setText] = useState("");
  const [f, setF] = useState(null);
  const [err, setErr] = useState("");
  const bind = (k) => ({ value: f[k] ?? "", onChange: (e) => setF({ ...f, [k]: e.target.value }) });
  const extract = async () => {
    setErr("");
    try { setF({ ...(await api.post("/opportunities/extract", { text })), description: text, url: "" }); } catch (e) { setErr(e.message); }
  };
  const publish = async () => {
    setErr("");
    try {
      const r = await api.post("/opportunities", { ...f, required_skills: typeof f.required_skills === "string" ? f.required_skills.split(",") : f.required_skills });
      onDone(r.outcome === "added" ? "Published. Agents are matching students and will notify strong matches."
        : r.outcome === "blocked" ? "Blocked by safety checks (looks like a scam or contains suspicious instructions)."
          : `Not added: ${r.outcome}.`);
    } catch (e) { setErr(e.message); }
  };
  return (
    <Modal title="Post an internship" onClose={onClose} wide>
      <Alert>{err}</Alert>
      {!f ? (
        <div className="form">
          <Field label="Paste the job description" hint="The Discovery Agent extracts title, skills, duration, stipend and eligibility criteria for you to review.">
            <textarea value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: 220 }} placeholder="e.g. Data Science Intern at Acme Analytics, Bengaluru. 6 months, ₹15,000/month. Python, SQL, pandas. CSE/AI students with CGPA 7.0+…" />
          </Field>
          <div className="row"><Button kind="primary" onClick={extract}>Extract details with AI</Button><button className="btn" onClick={() => setF({ description: text, required_skills: [], eligible_branches: [], mode: "onsite" })}>Fill in manually</button></div>
        </div>
      ) : (
        <div className="form">
          <div className="spread"><span className="small muted">Review what the agent extracted. Empty cutoffs mean the employer did not state one.</span><Mode mode={f.mode_used} /></div>
          <div className="form-row">
            <Field label="Title"><input {...bind("title")} /></Field><Field label="Company"><input {...bind("company")} /></Field>
          </div>
          <div className="form-row">
            <Field label="Location"><input {...bind("location")} /></Field>
            <Field label="Mode"><select {...bind("mode")}>{["onsite", "hybrid", "remote"].map((m) => <option key={m}>{m}</option>)}</select></Field>
            <Field label="Duration (weeks)"><input type="number" {...bind("duration_weeks")} /></Field>
            <Field label="Stipend"><input {...bind("stipend")} /></Field>
          </div>
          <div className="form-row">
            <Field label="Apply link (required)"><input {...bind("url")} placeholder="https://…" /></Field>
            <Field label="Deadline"><input type="date" {...bind("deadline")} /></Field>
          </div>
          <Field label="Required skills (comma separated)"><input value={Array.isArray(f.required_skills) ? f.required_skills.join(", ") : f.required_skills} onChange={(e) => setF({ ...f, required_skills: e.target.value })} /></Field>
          <div className="form-row">
            <Field label="Min CGPA"><input type="number" step="0.1" {...bind("min_cgpa")} /></Field>
            <Field label="Max active backlogs"><input type="number" {...bind("max_active_backlogs")} /></Field>
            <Field label="Min semester"><input type="number" {...bind("min_semester")} /></Field>
          </div>
          <div><div className="small muted">Eligible branches (none ticked = any branch)</div>
            <div className="row mt">{BRANCHES.map((b) => (
              <label key={b} className="check-row"><input type="checkbox" checked={(f.eligible_branches || []).includes(b)}
                onChange={(e) => setF({ ...f, eligible_branches: e.target.checked ? [...(f.eligible_branches || []), b] : f.eligible_branches.filter((x) => x !== b) })} />{b}</label>))}</div></div>
          <Field label="Description"><textarea {...bind("description")} /></Field>
          <div className="row"><Button kind="primary" onClick={publish}>Publish</Button><button className="btn" onClick={() => setF(null)}>Back</button></div>
        </div>
      )}
    </Modal>
  );
}

