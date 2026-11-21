import { useState } from "react";
import { api } from "../api";
import { Logo } from "../components/Common";
import { Alert, Badge, Button, Card, Chips, Empty, Field, Mode, Ring, Tabs, fmtDate, fmtTime, useLoad } from "../ui";

const JOURNEY = [["SAVED", "Prepare"], ["APPLIED", "Applied"], ["INTERVIEW", "Interview"], ["OFFERED", "Offer"],
  ["NOC_PENDING", "NOC"], ["ONGOING", "Internship"], ["COMPLETED", "Report"], ["GRADE_PENDING", "Grading"], ["GRADED", "Graded"]];
const POS = { NOC_CHANGES: 3, GRADE_CHANGES: 7 };
const RUBRIC = { weekly_consistency: ["Weekly progress & consistency", 25], technical_depth: ["Technical depth & deliverables", 30],
  mentor_evaluation: ["Industry mentor evaluation", 25], report_presentation: ["Final report & presentation", 20] };

function useForm(init) {
  const [f, setF] = useState(init);
  return [f, (k) => ({ value: f[k] ?? "", onChange: (e) => setF({ ...f, [k]: e.target.value }) }), setF];
}

export default function RecordPage({ id, me }) {
  const [d, reload, err] = useLoad(() => api.get(`/records/${id}`), [id]);
  const [tab, setTab] = useState(null);
  const [error, setError] = useState("");
  const [agentMsg, setAgentMsg] = useState(null);
  if (!d) return err ? <Alert>{err}</Alert> : <p>Loading…</p>;
  const { record: r, opportunity: o, student: s } = d;
  const role = me.user.role;
  const idx = POS[r.stage] ?? JOURNEY.findIndex(([k]) => k === r.stage);

  const act = async (path, body) => {
    setError("");
    try {
      const res = await api.post(path, body);
      if (res.agents?.length) setAgentMsg(res.agents);
      await reload();
      return res;
    } catch (e) { setError(e.message); }
  };

  const tabs = [["overview", "Overview"], ["kit", "Application kit"]];
  if (r.offer) tabs.push(["offer", "Offer & NOC"]);
  if (["ONGOING", "COMPLETED", "GRADE_PENDING", "GRADE_CHANGES", "GRADED"].includes(r.stage)) tabs.push(["progress", "Progress & logs"]);
  if (d.evaluations.length) tabs.push(["grade", "Evaluation"]);
  tabs.push(["trail", "Approvals & activity"]);
  const defaultTab = role === "mentor" ? "progress" : r.stage === "SAVED" ? "kit" : ["ONGOING", "COMPLETED"].includes(r.stage) ? "progress"
    : ["GRADE_PENDING", "GRADED"].includes(r.stage) ? "grade" : r.stage === "NOC_PENDING" && role === "faculty" ? "offer" : "overview";
  const cur = tabs.some(([k]) => k === tab) ? tab : tabs.some(([k]) => k === defaultTab) ? defaultTab : "overview";
  const ctx = { d, r, o, s, me, role, act, reload, setError };

  return (
    <>
      <a href={role === "student" ? "#/applications" : role === "mentor" ? "#/" : "#/approvals"}>← Back</a>
      <Card className="mt">
        <div className="spread" style={{ alignItems: "flex-start" }}>
          <div className="row" style={{ gap: 14, alignItems: "flex-start" }}>
            <Logo name={o.company} size={52} />
            <div>
              <h1>{o.title}</h1>
              <div className="muted">{o.company} · {o.location} · {r.id}{role !== "student" && <> · <b>{s.name}</b> ({[s.usn, `${s.department} sem ${s.semester}`].filter(Boolean).join(", ")})</>}</div>
              <div className="row mt"><Badge value={r.stage} />{r.progress_health && <Badge value={r.progress_health.status} />}
                {d.mentor && <span className="small muted">Mentor: {d.mentor.name}</span>}</div>
            </div>
          </div>
          {r.match?.score != null && <Ring value={r.match.score} size={64} />}
        </div>
        <div className="steps">
          {JOURNEY.map(([k, l], i) => <div key={k} className={`s ${i < idx ? "done" : ""} ${i === idx ? "now" : ""}`}>{l}</div>)}
        </div>
      </Card>
      <Alert>{error}</Alert>
      {agentMsg && <Alert tone="ok"><b>Agents acted:</b> {agentMsg.join(" · ")} <a style={{ float: "right" }} onClick={() => setAgentMsg(null)}>dismiss</a></Alert>}
      <NextStep {...ctx} />
      <Tabs tabs={tabs} value={cur} onChange={setTab} />
      {cur === "overview" && <Overview {...ctx} />}
      {cur === "kit" && <Kit {...ctx} />}
      {cur === "offer" && <OfferTab {...ctx} />}
      {cur === "progress" && <Progress {...ctx} />}
      {cur === "grade" && <Grade {...ctx} />}
      {cur === "trail" && <Trail {...ctx} />}
    </>
  );
}

// ------------------------------------------------------------ next step (role aware)
function NextStep({ d, r, o, role, act }) {
  const base = `/records/${r.id}`;
  const today = new Date().toISOString().slice(0, 10);
  const [f, bind] = useForm({ applied_on: today, start_date: today, duration_weeks: o.duration_weeks || 8, stipend: o.stipend,
    offer_ref: r.offer?.offer_ref || "", week: (d.logs.at(-1)?.week || 0) + 1, hours: 30, score: 8, mentor_id: "" });
  const [showOffer, setShowOffer] = useState(r.stage === "NOC_CHANGES");
  const [mentors] = useLoad(() => (role === "faculty" ? api.get("/mentors") : Promise.resolve([])), [role]);
  const pending = [...d.approvals].reverse().find((a) => a.decision === "PENDING");
  const lastRemark = [...d.approvals].reverse().find((a) => a.decision === "CHANGES_REQUESTED");

  if (role === "student") {
    if (r.stage === "SAVED") return (
      <Card title="Next: apply on the company site" subtitle="The portal never submits for you. Use your kit below, apply, then mark it here.">
        <div className="row"><a className="btn primary lg" href={o.url} target="_blank" rel="noreferrer">1. Open the application page ↗</a></div>
        <div className="form-row mt">
          <Field label="2. Date you applied"><input type="date" {...bind("applied_on")} /></Field>
          <Field label="Application / reference ID (optional)"><input {...bind("reference")} /></Field>
        </div>
        <div className="row mt">
          <Button kind="green" onClick={() => act(`${base}/status`, { stage: "APPLIED", applied_on: f.applied_on, reference: f.reference })}>I've applied</Button>
          <Button kind="red" onClick={() => act(`${base}/status`, { stage: "WITHDRAWN" })}>Not applying</Button>
        </div>
      </Card>);
    if (["APPLIED", "INTERVIEW", "NOC_CHANGES"].includes(r.stage)) return (
      <Card title={r.stage === "NOC_CHANGES" ? "Your coordinator asked for changes" : "Any update from the company?"}>
        {r.stage === "NOC_CHANGES" && lastRemark && <Alert tone="warn">“{lastRemark.remarks}” · {lastRemark.actor_name}</Alert>}
        {!showOffer ? (
          <div className="row">
            <Button kind="primary" onClick={() => setShowOffer(true)}>I got an offer 🎉</Button>
            {r.stage === "APPLIED" && <Button onClick={() => act(`${base}/status`, { stage: "INTERVIEW" })}>I have an interview</Button>}
            <Button kind="red" onClick={() => act(`${base}/status`, { stage: "NOT_SELECTED", note: prompt("Any feedback from the company? (optional)") || "" })}>Not selected</Button>
          </div>
        ) : (
          <div className="form">
            <div className="form-row">
              <Field label="Offer letter reference"><input {...bind("offer_ref")} /></Field>
              <Field label="Start date"><input type="date" {...bind("start_date")} /></Field>
              <Field label="Duration (weeks)"><input type="number" {...bind("duration_weeks")} /></Field>
              <Field label="Stipend"><input {...bind("stipend")} /></Field>
            </div>
            <Field label="Notes (optional)"><input {...bind("notes")} /></Field>
            <div className="row"><Button kind="primary" onClick={() => act(`${base}/offer`, f)}>Submit offer for NOC approval</Button>
              <button className="btn ghost" onClick={() => setShowOffer(false)}>Cancel</button></div>
            <div className="small muted">The Approval Agent checks the offer against the posting and college policy, then sends it to your coordinator.</div>
          </div>
        )}
      </Card>);
    if (r.stage === "ONGOING") return <LogForms base={base} d={d} act={act} />;
    const wait = { OFFERED: "The Approval Agent is checking your offer.", NOC_PENDING: "Your offer is with your coordinator for NOC approval.",
      COMPLETED: "Report submitted. Waiting for your mentor's final rating.", GRADE_PENDING: "Your draft grade is waiting for the coordinator's sign-off.",
      GRADE_CHANGES: "The coordinator asked for a re-evaluation." }[r.stage];
    if (r.stage === "GRADED") { const ev = d.evaluations.at(-1); return <Alert tone="ok"><b>Internship complete.</b> Final grade {ev.grade} ({ev.total}/100).</Alert>; }
    return wait ? <Alert tone="info">{wait}</Alert> : null;
  }

  if (role === "faculty" && ["NOC_PENDING", "GRADE_PENDING"].includes(r.stage)) {
    const gate = r.stage === "NOC_PENDING" ? "NOC" : "GRADE";
    const ev = d.evaluations.at(-1);
    return (
      <Card title={gate === "NOC" ? "Your decision: NOC approval" : "Your decision: grade sign-off"}>
        {pending && <Alert tone={pending.agent_recommendation.startsWith("APPROVE") ? "ok" : "warn"}><b>Approval Agent:</b> {pending.agent_recommendation}</Alert>}
        {gate === "NOC" && r.offer && <div className="kv mt"><span className="k">Offer</span><span>{r.offer.offer_ref} · starts {r.offer.start_date} · {r.offer.duration_weeks} weeks · {r.offer.stipend}</span>
          <span className="k">Eligibility</span><span>{r.eligibility?.summary}</span></div>}
        {gate === "GRADE" && ev && <p className="mt">Draft grade <b>{ev.grade}</b> ({ev.total}/100). See the Evaluation tab for the breakdown.</p>}
        <div className="form mt">
          {gate === "NOC" && <Field label="Industry mentor for this intern"><select {...bind("mentor_id")}><option value="">Choose a mentor…</option>
            {(mentors || []).map((m) => <option key={m.id} value={m.id}>{m.name} · {m.title}</option>)}</select></Field>}
          <Field label="Remarks (required to reject or request changes)"><textarea {...bind("remarks")} /></Field>
          <div className="row">
            <Button kind="green" onClick={() => act(`${base}/decision`, { gate, decision: "APPROVED", remarks: f.remarks || "", mentor_id: f.mentor_id })}>{gate === "NOC" ? "Approve & issue NOC" : "Approve & publish grade"}</Button>
            <Button kind="amber" onClick={() => act(`${base}/decision`, { gate, decision: "CHANGES_REQUESTED", remarks: f.remarks || "" })}>Request changes</Button>
            {gate === "NOC" && <Button kind="red" onClick={() => act(`${base}/decision`, { gate, decision: "REJECTED", remarks: f.remarks || "" })}>Reject</Button>}
          </div>
        </div>
      </Card>);
  }

  if (role === "mentor" && ["ONGOING", "COMPLETED"].includes(r.stage)) {
    const fr = r.final_report || {};
    return (
      <Card title="Your final rating" subtitle={fr.mentor_score != null ? `Submitted: ${fr.mentor_score}/10. You can update it.` : "Give it once the intern finishes (or any time during the internship)."}>
        <div className="form-row">
          <Field label="Overall rating (0-10)"><input type="number" min="0" max="10" step="0.5" {...bind("score")} /></Field>
        </div>
        <Field label="Feedback for the student and coordinator"><textarea {...bind("feedback")} /></Field>
        <div className="mt"><Button kind="primary" onClick={() => act(`${base}/rating`, { score: Number(f.score), feedback: f.feedback || "" })}>Submit rating</Button></div>
      </Card>);
  }
  return null;
}

function LogForms({ base, d, act }) {
  const [mode, setMode] = useState("log");
  const [f, bind, setF] = useForm({ week: (d.logs.at(-1)?.week || 0) + 1, hours: 30 });
  return (
    <Card title="Your internship" actions={<Tabs tabs={[["log", "Weekly log"], ["report", "Finish internship"]]} value={mode} onChange={setMode} />}>
      {mode === "log" ? (
        <div className="form">
          <div className="form-row">
            <Field label="Week"><input type="number" min="1" {...bind("week")} /></Field>
            <Field label="Hours worked" hint="Policy target: 30 hrs/week"><input type="number" {...bind("hours")} /></Field>
          </div>
          <Field label="What did you work on?"><textarea {...bind("tasks")} placeholder="Tasks, features, experiments, meetings…" /></Field>
          <Field label="What did you learn? (optional)"><input {...bind("learnings")} /></Field>
          <Field label="Links to your work (repo, doc, demo)"><input {...bind("artifacts")} /></Field>
          <Button kind="primary" onClick={async () => { const r = await act(`${base}/logs`, { ...f, week: Number(f.week), hours: Number(f.hours) }); if (r) setF({ week: Number(f.week) + 1, hours: 30 }); }}>Submit week {f.week} log</Button>
        </div>
      ) : (
        <div className="form">
          <Field label="Final report summary" hint="What you built, results, what you learned (80+ characters)"><textarea {...bind("summary")} style={{ minHeight: 140 }} /></Field>
          <Field label="Link to the full report / slides"><input {...bind("link")} /></Field>
          <Button kind="green" onClick={() => act(`${base}/report`, { summary: f.summary || "", link: f.link || "" })}>Submit final report</Button>
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------ tabs
function Overview({ r, o }) {
  const m = r.match || {};
  return (
    <div className="grid2">
      <Card title="Fit when you applied">
        <p>{m.why}</p>
        <div className="small muted">You have</div><Chips items={m.have} tone="green" />
        <div className="small muted mt">You lack</div><Chips items={m.missing} tone="red" empty="nothing" />
        {m.improve && <p className="small mt"><b>To improve:</b> {m.improve}</p>}
      </Card>
      <Card title="Eligibility" subtitle={r.eligibility?.summary}>
        <table><tbody>{(r.eligibility?.checks || []).map((c) => <tr key={c.rule}><td><Badge value={c.status} /></td><td className="small">{c.message}</td></tr>)}</tbody></table>
        <div className="small mt"><a href={o.url} target="_blank" rel="noreferrer">Company application page ↗</a></div>
        {r.submission && <p className="small">Applied on {r.submission.applied_on}{r.submission.reference && ` · ref ${r.submission.reference}`}</p>}
      </Card>
    </div>
  );
}

function Kit({ r, role, act }) {
  const k = r.application;
  const [copied, setCopied] = useState(false);
  if (!k) return <Empty title="No kit yet" />;
  return (
    <>
      <Card title="Tailored cover letter" subtitle={`Prepared by the Application Agent · version ${k.version}`}
        actions={<><Mode mode={k.mode} />
          <button className="btn" onClick={() => { navigator.clipboard.writeText(k.cover_letter); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>{copied ? "Copied ✓" : "Copy"}</button>
          {role === "student" && ["SAVED", "APPLIED", "INTERVIEW"].includes(r.stage) && <Button onClick={() => act(`/records/${r.id}/kit`)}>Regenerate</Button>}</>}>
        <div className="letter">{k.cover_letter}</div>
      </Card>
      <div className="grid3">
        <Card title="Resume tips for this role"><ul className="small">{(k.resume_tips || []).map((t, i) => <li key={i}>{t}</li>)}</ul></Card>
        <Card title="Likely interview questions"><ul className="small">{(k.interview_prep || []).map((t, i) => <li key={i}>{t}</li>)}</ul></Card>
        <Card title="Checklist">{(k.checklist || []).map((c) => <div key={c.item} className="small" style={{ padding: "3px 0" }}><span style={{ color: c.ok ? "var(--green)" : "var(--red)" }}>{c.ok ? "✓" : "✗"}</span> {c.item}</div>)}</Card>
      </div>
    </>
  );
}

function OfferTab({ r }) {
  return (
    <div className="grid2">
      <Card title="Offer details">
        <div className="kv">
          <span className="k">Reference</span><span>{r.offer.offer_ref}</span>
          <span className="k">Start date</span><span>{r.offer.start_date}</span>
          <span className="k">Duration</span><span>{r.offer.duration_weeks} weeks</span>
          <span className="k">Stipend</span><span>{r.offer.stipend || "-"}</span>
          {r.offer.notes && <><span className="k">Notes</span><span>{r.offer.notes}</span></>}
        </div>
      </Card>
      <Card title="No Objection Certificate" actions={r.noc && <button className="btn" onClick={() => { const w = window.open(""); w.document.write(`<pre style="font:15px Georgia;padding:40px;white-space:pre-wrap">${r.noc.letter}</pre>`); w.print(); }}>Print</button>}>
        {r.noc ? <><p className="small muted">Issued by {r.noc.issued_by} on {fmtDate(r.noc.issued_at)} · {r.noc.ref}</p><div className="letter">{r.noc.letter}</div></>
          : <p className="muted">Not issued yet. It is generated when the coordinator approves the offer.</p>}
      </Card>
    </div>
  );
}

function Progress({ d, r, role, act }) {
  const h = r.progress_health;
  return (
    <>
      {h && (
        <div className="stats">
          <div className="stat"><div className="stat-value"><Badge value={h.status} /></div><div className="stat-label mt">Progress health</div></div>
          <div className="stat"><div className="stat-value">{h.weeks_logged}/{h.expected_weeks || h.duration_weeks}</div><div className="stat-label">weeks logged / due</div></div>
          <div className="stat"><div className="stat-value">{h.total_hours}</div><div className="stat-label">hours logged</div></div>
          <div className="stat"><div className="stat-value">{h.verified_logs}</div><div className="stat-label">logs verified by mentor</div></div>
        </div>
      )}
      <div className="split">
        <Card title="Weekly logs">
          {d.logs.length === 0 && <p className="muted">No logs yet.</p>}
          {d.logs.map((l) => (
            <div key={l.id} style={{ borderBottom: "1px solid var(--line)", padding: "10px 0" }}>
              <div className="spread"><b>Week {l.week} · {l.hours} hrs</b>
                <span className="row">{(l.co_mapping || []).map((c) => <span key={c} className="chip">{c}</span>)}
                  {l.mentor_verified ? <Badge value="APPROVED" label="Verified" /> : role === "mentor"
                    ? <Button kind="primary" onClick={() => act(`/logs/${l.id}/verify`, { remarks: prompt("Remarks for this week (optional)") || "" })}>Verify</Button>
                    : <Badge value="PENDING" label="Awaiting mentor" />}</span></div>
              <div className="small mt">{l.tasks}</div>
              {l.learnings && <div className="small muted">Learned: {l.learnings}</div>}
              {l.artifacts && <a className="small" href={l.artifacts} target="_blank" rel="noreferrer">{l.artifacts}</a>}
              {l.mentor_remarks && <div className="small" style={{ color: "var(--green)" }}>Mentor: “{l.mentor_remarks}”</div>}
            </div>
          ))}
        </Card>
        <div>
          {h && (
            <Card title="Progress Agent" actions={<Mode mode={h.mode} />}>
              {h.summary && <p className="small">{h.summary}</p>}
              {h.missing_weeks.length > 0 && <Alert tone="error">Missing weeks: {h.missing_weeks.join(", ")}</Alert>}
              {h.shortfalls.map((s, i) => <div key={i} className="small" style={{ color: "var(--amber)" }}>• {s}</div>)}
              {h.status === "ON_TRACK" && <Alert tone="ok">On track with the 30 hrs/week policy.</Alert>}
            </Card>
          )}
          {r.milestones && (
            <Card title="Milestones">
              {r.milestones.map((m) => (
                <div key={m.name} className="spread" style={{ padding: "6px 0" }}>
                  <div><div className="small"><b>{m.name}</b></div><div className="small muted">Week {m.week} · due {m.due}</div></div>
                  <Badge value={m.status === "DONE" ? "APPROVED" : "PENDING"} label={m.status === "DONE" ? "Done" : "Pending"} />
                </div>
              ))}
            </Card>
          )}
          {r.final_report?.summary && <Card title="Final report"><p className="small">{r.final_report.summary}</p>{r.final_report.link && <a className="small" href={r.final_report.link}>{r.final_report.link}</a>}</Card>}
        </div>
      </div>
    </>
  );
}

function Grade({ d, r }) {
  const ev = d.evaluations.at(-1);
  const j = JSON.parse(ev.justification || "{}");
  return (
    <div className="split">
      <Card title={`Final grade ${ev.status === "FINAL" ? "" : "(draft)"}`} actions={<><Badge value={ev.status} /><Mode mode={j.mode} /></>}>
        <div className="row" style={{ gap: 24 }}>
          <div style={{ fontSize: 54, fontWeight: 800, color: "var(--brand)" }}>{ev.grade}</div>
          <div><div style={{ fontSize: 22, fontWeight: 700 }}>{ev.total} / 100</div><div className="small muted">Version {ev.version} of {d.evaluations.length}</div></div>
        </div>
        <table className="mt"><tbody>
          {Object.entries(RUBRIC).map(([k, [label, max]]) => (
            <tr key={k}><td>{label}</td><td style={{ width: 160 }}><div className="bar"><div style={{ width: `${(ev.scores[k] / max) * 100}%` }} /></div></td><td className="right"><b>{ev.scores[k]}</b> / {max}</td></tr>
          ))}
        </tbody></table>
        <p className="small muted mt">Marks are calculated by rules from your logs, the mentor's rating and the AI's 0-10 ratings of technical depth and report quality. The grade is final only after the coordinator signs it off.</p>
      </Card>
      <Card title="Evaluation Agent's notes">
        <p className="small">{j.text}</p>
        {j.co_attainment && Object.entries(j.co_attainment).map(([co, v]) => <div key={co} className="spread small" style={{ padding: "3px 0" }}><span>{co}</span><span className="chip">{v}</span></div>)}
        {r.final_report?.mentor_feedback && <p className="small mt"><b>Mentor:</b> “{r.final_report.mentor_feedback}” ({r.final_report.mentor_score}/10)</p>}
      </Card>
    </div>
  );
}

function Trail({ d }) {
  return (
    <div className="grid2">
      <Card title="Approval trail" subtitle="Append-only: decisions are never edited or deleted">
        {d.approvals.length === 0 && <p className="muted small">No approvals yet.</p>}
        <div className="timeline">
          {d.approvals.map((a) => (
            <div key={a.id} className={`item ${a.decision}`}>
              <div className="row"><b>{a.gate === "NOC" ? "NOC approval" : "Grade sign-off"}</b><Badge value={a.decision} /><span className="small muted">{fmtTime(a.ts)}</span></div>
              <div className="small">{a.actor_name}{a.actor_role !== "agent" && ` · ${a.actor_role}`}</div>
              {a.decision === "PENDING" && <div className="small muted">{a.agent_recommendation}</div>}
              {a.remarks && a.decision !== "PENDING" && <div className="small">“{a.remarks}”</div>}
            </div>
          ))}
        </div>
      </Card>
      <Card title="Activity" subtitle="What people and agents did on this record">
        {d.activity.map((a, i) => (
          <div key={i} className="spread small" style={{ padding: "5px 0", borderBottom: "1px solid var(--line)" }}>
            <span><Badge value={a.kind} label={a.kind === "agent" ? "agent" : a.kind === "human" ? "person" : a.kind} tone={a.kind === "agent" ? "violet" : a.kind === "human" ? "blue" : "red"} /> {a.actor}: {a.action.replace(/_/g, " ").toLowerCase()}</span>
            <span className="muted nowrap">{fmtTime(a.ts)}</span>
          </div>
        ))}
      </Card>
    </div>
  );
}
