import { useState } from "react";
import { api } from "../../api";
import { RunModal } from "../Activity";
import { Alert, Badge, Button, Card, Stat, fmtTime, useLoad } from "../../ui";

export default function AdminHome({ me }) {
  const [d, reload] = useLoad(() => api.get("/admin/overview"));
  const [run, setRun] = useState(null);
  const [msg, setMsg] = useState("");
  if (!d) return <p>Loading…</p>;
  return (
    <>
      <div className="page-head"><div><h1>System overview</h1><div className="muted">Job boards last synced {d.boards_synced ? fmtTime(d.boards_synced) : "never"}</div></div>
        <div className="row">
          <a className="btn" href="#/activity">⚡ Open agent activity</a>
          <Button onClick={async () => { await api.post("/admin/sweep"); setMsg("Scheduled sweep started. It only calls the AI if something changed."); setTimeout(reload, 4000); }}>Run scheduled sweep now</Button>
          {me.permissions.includes("reset_demo") && <Button kind="red" onClick={async () => { if (confirm("Reset all demo data? Everyone will be logged out.")) { await api.post("/admin/reset"); window.location.reload(); } }}>Reset demo data</Button>}
        </div></div>
      <Alert tone="info">{msg}</Alert>
      <div className="stats">
        <Stat label="Students" value={d.students} tone="blue" />
        <Stat label="Open postings" value={d.open_postings} tone="green" hint={`${d.blocked_postings} blocked by safety checks`} />
        <Stat label="Tracked records" value={d.records} tone="violet" />
        <Stat label="AI / tool calls" value={`${d.llm_calls} / ${d.tool_calls}`} />
      </div>
      <Card title="Worklet 10 agents (PPT slide 15)" subtitle="How many times each agent has been called so far">
        <div className="grid3">{d.worklet_agents.map((w) => (
          <div key={w.name} className="spread" style={{ padding: "8px 12px", border: "1px solid var(--line)", borderRadius: 10 }}>
            <span>🤖 <b>{w.name}</b></span><Badge value={w.calls ? "APPROVED" : "PENDING"} label={`${w.calls} calls`} /></div>))}</div>
      </Card>
      <Card title="Course concepts in this portal" subtitle="Where each of the 12 core concepts lives, with live evidence from the audit log">
        <table><thead><tr><th>#</th><th>Concept</th><th>Where</th><th>Evidence so far</th></tr></thead>
          <tbody>{d.concepts.map((c) => (
            <tr key={c.n}><td><b>{c.n}</b></td><td><b>{c.name}</b></td><td className="small">{c.where}</td><td className="small nowrap">{c.evidence}</td></tr>))}
            <tr><td><b>13</b></td><td><b>Discipline-specific agents</b></td><td className="small">Worklet 10: Internship Application & Tracking Portal</td><td className="small">six agents above</td></tr>
            <tr><td><b>14</b></td><td><b>Capstone</b></td><td className="small">This portal end to end</td><td className="small">{d.records} records</td></tr>
          </tbody></table>
      </Card>
      <Card title="Recent runs" subtitle="Each run: Gateway → agents → tools / AI → result. Click one for the full trace.">
        <table><tbody>{d.runs.map((r) => (
          <tr key={r.run_id} className="click" onClick={() => setRun(r.run_id)}>
            <td className="small muted nowrap">{fmtTime(r.started_at)}</td><td className="small"><b>{r.run_id}</b><div className="muted">{r.channel}</div></td>
            <td className="small">{r.goal}</td><td><Badge value={r.status === "done" ? "APPROVED" : r.status === "failed" ? "REJECTED" : "PENDING"} label={r.status} /></td>
            <td className="small right nowrap">{r.events} events</td></tr>))}</tbody></table>
      </Card>
      {run && <RunModal runId={run} onClose={() => setRun(null)} showPrompts />}
    </>
  );
}
