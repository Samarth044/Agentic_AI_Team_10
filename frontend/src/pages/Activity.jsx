import { useState } from "react";
import { api } from "../api";
import { Feed, useActivity } from "../components/Activity";
import { Badge, Button, Card, Modal, Tabs, fmtTime, useLoad, usePoll } from "../ui";

const FILTERS = [["all", "Everything"], ["agent", "Agent calls"], ["tool", "MCP tool calls"], ["llm", "AI model calls"],
  ["memory", "Memory"], ["human", "People"], ["loop", "Plan / act / observe"], ["guardrail", "Guardrails"]];

const STAFF_ONLY = ["Policy Agent", "Ops Agent"];

export function Roster({ me }) {
  const [d, reload] = useLoad(() => api.get("/activity/agents"));
  usePoll(reload, true, 3000);
  if (!d) return null;
  const student = me.user.role === "student";
  return (
    <Card title={`Agents: ${d.ran} of ${d.total} have run so far`}
      subtitle="Agents start on their own when the thing they handle happens. Grey = waiting for its trigger.">
      <div className="roster">
        {d.agents.map((a) => (
          <div key={a.name} className={`agent-tile ${a.calls ? "on" : ""}`}>
            <div className="spread">
              <b>🤖 {a.name}</b>
              <span className={`badge ${a.calls ? "green" : "grey"}`}>{a.calls ? `ran ${a.calls}×` : "waiting"}</span>
            </div>
            {a.worklet && <span className="small" style={{ color: "var(--violet)" }}>Worklet 10 agent</span>}
            <div className="small muted">{a.calls && a.last ? `Last run ${fmtTime(a.last)}` : a.trigger}</div>
            {student && !a.calls && STAFF_ONLY.includes(a.name) && <div className="small muted">(runs for the coordinator/admin, not shown in your log)</div>}
            {a.name === "Expert Panel" && (
              <div className="chips mt">{d.reviewers.map((r) => <span key={r.name} className={`chip ${r.calls ? "green" : ""}`}>{r.name}{r.calls ? ` ✓` : ""}</span>)}</div>
            )}
          </div>
        ))}
      </div>
      {me.user.role === "admin" && <DemoJourney onDone={reload} />}
    </Card>
  );
}

function DemoJourney({ onDone }) {
  const [st, reload, , setSt] = useLoad(() => api.get("/admin/demo"));
  usePoll(() => reload().then(onDone), st?.state === "running", 2000);
  if (!st) return null;
  const start = async () => {
    if (!confirm("Run the full internship journey for the demo student? It drives every agent for real (about 20 AI calls, under a minute).")) return;
    setSt(await api.post("/admin/demo"));
  };
  return (
    <div className="demo-bar">
      <div>
        <b>Demo journey</b>
        <div className="small muted">
          {st.state === "running" ? `Step ${st.done}/${st.total}: ${st.step}`
            : st.state === "done" ? <>All agents ran. See record <a href={`#/records/${st.record_id}`}>{st.record_id}</a> and the log below.</>
              : st.state === "error" ? <span style={{ color: "var(--red)" }}>{st.error}</span>
                : "One click: apply → offer → NOC → 3 weekly logs → report → rating → grade, plus chat, panel, research, a rule draft and a health check. Labelled [Demo] in the log."}
        </div>
        {st.state === "running" && st.total > 0 && <div className="bar mt"><div style={{ width: `${(100 * st.done) / st.total}%` }} /></div>}
      </div>
      <Button kind="primary" disabled={st.state === "running"} onClick={start}>{st.state === "running" ? "Running…" : "▶ Run demo journey"}</Button>
    </div>
  );
}

export default function ActivityPage({ me }) {
  const events = useActivity(true, 600);
  const [runs, reloadRuns] = useLoad(() => api.get("/activity/runs"));
  const [filter, setFilter] = useState("all");
  const [run, setRun] = useState(null);
  const isAdmin = me.user.role === "admin";
  const shown = (filter === "all" ? events : events.filter((e) => e.kind === filter || (filter === "agent" && e.kind === "run"))).slice().reverse();
  const count = (k, a) => events.filter((e) => e.kind === k && (!a || e.action === a)).length;
  const agents = [...new Set(events.filter((e) => e.kind === "agent" && e.action === "called").map((e) => e.actor))];
  return (
    <>
      <div className="page-head">
        <div><h1>Agent activity</h1><div className="muted">Every run, agent call, skill load, MCP tool call, AI call, memory access and human decision, live. {me.user.role === "student" ? "You see your own runs." : me.user.role === "admin" ? "You see everything, including prompts." : "You see runs for your students."}</div></div>
        <button className="btn" onClick={reloadRuns}>Refresh runs</button>
      </div>
      <div className="stats">
        <div className="stat"><div className="stat-value">{(runs || []).length}</div><div className="stat-label">runs</div></div>
        <div className="stat"><div className="stat-value">{count("agent", "called")}</div><div className="stat-label">agent calls</div></div>
        <div className="stat"><div className="stat-value">{count("tool")}</div><div className="stat-label">MCP tool calls</div></div>
        <div className="stat"><div className="stat-value">{count("llm")}</div><div className="stat-label">AI model calls</div></div>
      </div>
      <Roster me={me} />
      <div className="split">
        <Card title="Live log" subtitle="Newest first">
          <Tabs tabs={FILTERS} value={filter} onChange={setFilter} />
          {shown.length ? <Feed events={shown} onRun={setRun} showPrompts={isAdmin} /> : <p className="muted">No events yet.</p>}
        </Card>
        <Card title="Runs" subtitle="One run per request, chat message or scheduler sweep">
          {(runs || []).map((r) => (
            <div key={r.run_id} className="run-row" onClick={() => setRun(r.run_id)}>
              <div className="spread"><b className="small">{r.run_id}</b><Badge value={r.status === "done" ? "APPROVED" : r.status === "failed" ? "REJECTED" : "PENDING"} label={r.status} /></div>
              <div className="small">{r.goal}</div>
              <div className="small muted">{r.channel} · {r.agents} agent call(s) · {r.events} events · {fmtTime(r.started_at)}{r.ms ? ` · ${(r.ms / 1000).toFixed(1)}s` : ""}</div>
            </div>
          ))}
        </Card>
      </div>
      {run && <RunModal runId={run} onClose={() => setRun(null)} showPrompts={isAdmin} />}
    </>
  );
}

export function RunModal({ runId, onClose, showPrompts }) {
  const [data] = useLoad(() => api.get(`/activity/runs/${runId}`), [runId]);
  const r = data?.run;
  const d = data?.events;
  return (
    <Modal title={`Run ${runId}`} onClose={onClose} wide>
      {r && <p className="small muted">{r.goal} · channel {r.channel} · {r.status}{r.ms ? ` in ${(r.ms / 1000).toFixed(1)}s` : ""}</p>}
      {r?.session && (
        <details className="mt"><summary className="small">Session memory of this run (short-term)</summary>
          <pre className="json">{JSON.stringify(r.session, null, 2)}</pre></details>
      )}
      <div className="mt"><Feed events={d || []} showPrompts={showPrompts} /></div>
    </Modal>
  );
}
