import { useState } from "react";
import { api } from "../../api";
import Graph from "../../components/Graph";
import { Badge, Button, Card, Chips, Tabs, fmtTime, useLoad } from "../../ui";

export default function Agents() {
  const [d] = useLoad(() => api.get("/admin/agents"));
  const [tab, setTab] = useState("agents");
  if (!d) return <p>Loading…</p>;
  return (
    <>
      <div className="page-head"><div><h1>Agents, MCP & runtime</h1><div className="muted">{d.agents.length} agents run inside one runtime. Each has its own skill file, an allow-list of tools reached over MCP, memory and an audit trail.</div></div></div>
      <Tabs tabs={[["agents", `Agents (${d.agents.length})`], ["runtime", "Runtime (OpenClaw-style)"], ["mcp", "MCP server"], ["workflow", "Workflow graph"], ["skills", `Skills (${d.skills.length})`]]} value={tab} onChange={setTab} />
      {tab === "agents" && (
        <div className="grid2">
          {d.agents.map((a) => (
            <Card key={a.name} title={`🤖 ${a.name}`} actions={<Badge value={a.calls ? "APPROVED" : "PENDING"} label={`${a.calls} calls`} />}>
              <p className="small">{a.description}</p>
              <div className="kv mt">
                <span className="k">Skill</span><span>{a.skill ? <code>skills/{a.skill}/SKILL.md</code> : <span className="muted">rules only (no AI skill)</span>}</span>
                <span className="k">Tools (via MCP)</span><span><Chips items={a.tools} empty="none" /></span>
                <span className="k">Runtime steps</span><span><Chips items={a.methods} empty="-" /></span>
              </div>
            </Card>
          ))}
        </div>
      )}
      {tab === "runtime" && <Runtime rt={d.runtime} />}
      {tab === "mcp" && <MCP />}
      {tab === "workflow" && (
        <Card title="Internship lifecycle" subtitle="Blue = agent acts on its own, amber = waits for a person. Hover an arrow for its condition.">
          <Graph g={d.graph} />
          <table className="mt"><tbody>{d.graph.edges.map((e, i) => <tr key={i}><td>{e.from}</td><td>→</td><td>{e.to}</td><td className="muted small">{e.label}</td></tr>)}</tbody></table>
        </Card>
      )}
      {tab === "skills" && (
        <Card subtitle="Progressive disclosure: only name + description are always known; the full SKILL.md is loaded into the prompt when the owning agent runs.">
          <table><thead><tr><th>Skill</th><th>Owner</th><th>Size</th><th>Loaded</th></tr></thead>
            <tbody>{d.skills.map((s) => <tr key={s.folder}><td><b>{s.name}</b><div className="small muted">{s.description}</div></td><td className="small">{s.owner}</td><td className="small muted nowrap">{s.chars} chars</td><td className="small">{s.loaded}×</td></tr>)}</tbody></table>
        </Card>
      )}
    </>
  );
}

function Runtime({ rt }) {
  const parts = [
    ["Interface (Gateway)", "Every web request, chat message, background event and scheduler sweep enters through the Gateway and becomes a run with a run id and a session.", "portal/runtime.py · Gateway, portal/main.py · gateway_interface middleware"],
    ["Runtime", "Each agent method is a runtime step: it is announced, timed and recorded (called → finished / failed). Nested steps join the same run; parallel branches keep the run.", "portal/runtime.py · Agent, @step, parallel()"],
    ["Skills", "SKILL.md files with name/description frontmatter. The body is loaded into the system prompt only when the owning agent thinks.", "skills/*/SKILL.md"],
    ["Tools", "Each agent has an allow-list. Calls outside it are blocked by a guardrail. Calls go over MCP to the portal MCP server.", "portal/connector.py, portal/mcp_client.py, mcp-server/portal_mcp_server.py"],
    ["Memory", "Session memory per run (saved with the run) and long-term memory per student in SQLite plus a Markdown file, recalled by relevance.", "portal/memory.py, data/memory/<student>.md"],
    ["Audit log", "Append-only: every run, agent call, skill load, tool call, AI call, memory access and human decision, in SQLite and logs/portal-audit.jsonl.", "portal/guardrails.py · audit()"],
  ];
  return (
    <>
      <Card title="How a request is handled" subtitle="Modelled on OpenClaw: one Gateway in front of an agent runtime">
        <div className="flow"><span>Channel: web / chat / event / scheduler</span><i>→</i><span>Gateway (run id + session)</span><i>→</i><span>Agent step</span><i>→</i><span>Load skill</span><i>→</i><span>Assemble context + memory</span><i>→</i><span>AI model</span><i>⇄</i><span>Tools over MCP</span><i>→</i><span>Persist + audit</span><i>→</i><span>Next agent or a person</span></div>
      </Card>
      <div className="stats">
        <div className="stat"><div className="stat-value">{rt.runs}</div><div className="stat-label">runs</div><div className="small muted">{rt.channels.map((c) => `${c.channel}: ${c.n}`).join(" · ")}</div></div>
        <div className="stat"><div className="stat-value">{rt.agent_calls}</div><div className="stat-label">agent calls</div></div>
        <div className="stat"><div className="stat-value">{rt.mcp_calls}/{rt.tool_calls}</div><div className="stat-label">tool calls over MCP</div></div>
        <div className="stat"><div className="stat-value">{rt.llm_calls}</div><div className="stat-label">AI model calls</div><div className="small muted">{rt.memories} memories stored</div></div>
      </div>
      <div className="grid2">{parts.map(([t, d, f]) => <Card key={t} title={t}><p className="small">{d}</p><div className="small muted"><code>{f}</code></div></Card>)}</div>
    </>
  );
}

function MCP() {
  const [st, reload] = useLoad(() => api.get("/admin/mcp"));
  const examples = { sql_query: '{"sql": "SELECT stage, COUNT(*) AS n FROM records GROUP BY stage"}', read_document: '{"name": "internship_policy.md"}',
    list_documents: "{}", campus_postings: '{"keyword": "react"}', calculator: '{"expression": "(8.6 - 0.75) * 10"}',
    get_student: '{"student_id": "s-1"}', live_job_boards: '{"keywords": ["software"]}', wikipedia_summary: '{"topic": "Infosys"}',
    extract_resume_text: '{"filename": "..."}' };
  const [name, setName] = useState("sql_query");
  const [args, setArgs] = useState(examples.sql_query);
  const [out, setOut] = useState(null);
  if (!st) return <p>Connecting to the MCP server…</p>;
  return (
    <>
      <Card title="Portal MCP server" actions={<><Badge value={st.connected ? "APPROVED" : "REJECTED"} label={st.connected ? "connected" : "not connected"} /><button className="btn" onClick={reload}>Refresh</button></>}>
        <div className="kv">
          <span className="k">Server</span><span>{st.server?.name} (MCP SDK {st.server?.version})</span>
          <span className="k">Protocol</span><span>{st.server?.protocol} over {st.server?.transport}</span>
          <span className="k">Started as</span><span><code>{st.server?.command}</code> (child process of the portal)</span>
          <span className="k">Handshake</span><span>initialize → tools/list → tools/call</span>
          {st.error && <><span className="k">Error</span><span style={{ color: "var(--red)" }}>{st.error}</span></>}
        </div>
      </Card>
      <div className="split">
        <Card title={`Tools listed by the server (${st.tools.length})`} subtitle="From the live tools/list response. Click one to try it.">
          <table><tbody>{st.tools.map((t) => (
            <tr key={t.name} className="click" onClick={() => { setName(t.name); setArgs(examples[t.name] || "{}"); setOut(null); }}>
              <td><b>{t.name}</b><div className="small muted">{t.description}</div></td>
              <td className="small muted">{Object.keys(t.input_schema?.properties || {}).join(", ") || "no args"}</td></tr>))}</tbody></table>
        </Card>
        <div>
          <Card title={`Call ${name} over MCP`}>
            <textarea value={args} onChange={(e) => setArgs(e.target.value)} style={{ fontFamily: "Consolas, monospace", fontSize: 12 }} />
            <div className="row mt"><Button kind="primary" onClick={async () => { try { setOut(await api.post(`/admin/tools/${name}`, JSON.parse(args))); reload(); } catch (e) { setOut({ error: e.message }); } }}>tools/call</Button>
              <button className="btn" onClick={() => { setName("sql_query"); setArgs('{"sql": "DELETE FROM records"}'); }}>Try a write (refused)</button></div>
            {out && <pre className="json mt">{JSON.stringify(out, null, 2)}</pre>}
          </Card>
          <Card title="Recent tool calls">
            {st.recent_calls.map((c, i) => (
              <div key={i} className="spread small" style={{ padding: "4px 0", borderBottom: "1px solid var(--line)" }}>
                <span>{c.ok === 0 || c.ok === false ? "✗" : "✓"} <b>{c.action}</b> · {c.actor}</span>
                <span className="muted nowrap">{c.transport} · {c.ms ?? "-"}ms · {fmtTime(c.ts).split(", ").pop()}</span>
              </div>))}
          </Card>
        </div>
      </div>
    </>
  );
}
