import { useState } from "react";
import { api } from "../../api";
import { Alert, Button, Card, Mode, fmtTime, useLoad } from "../../ui";

const ok = (v) => <span style={{ color: "var(--green)", fontWeight: 700 }}>✓ {v}</span>;
const bad = (v) => <span style={{ color: "var(--red)", fontWeight: 700 }}>✗ {v}</span>;

export default function Health({ me }) {
  const [d, reload, err] = useLoad(() => api.get("/admin/health"));
  const [res, setRes] = useState(null);
  if (!d) return err ? <Alert>{err}</Alert> : <p>The Ops Agent is checking the system…</p>;
  const s = d.signals, dx = d.diagnosis;
  return (
    <>
      <div className="page-head"><div><h1>System health</h1><div className="muted">The Ops Agent observes health signals and the last deployment log, diagnoses the cause, and applies a fix only after you approve.</div></div>
        <button className="btn" onClick={reload}>Re-check</button></div>
      <div className="grid2">
        <Card title="Signals">
          <div className="kv">
            <span className="k">Database tables</span><span>{s.missing_tables.length ? bad(`missing ${s.missing_tables.join(", ")}`) : ok("all present")}</span>
            <span className="k">AI provider key</span><span>{s.llm_key_set ? ok("set") : bad("not set")}</span>
            <span className="k">Last AI call</span><span>{s.llm_last_error ? bad(s.llm_last_error.slice(0, 80)) : ok("no errors")}</span>
            <span className="k">Agent skills</span><span>{s.missing_skills.length ? bad(s.missing_skills.join(", ")) : ok("all present")}</span>
            <span className="k">College documents</span><span>{s.missing_docs.length ? bad(s.missing_docs.join(", ")) : ok("all present")}</span>
            <span className="k">Web app build</span><span>{s.frontend_built ? ok("built") : bad("missing")}</span>
            <span className="k">Tool / AI errors</span><span>{s.recent_errors}</span>
            <span className="k">Job boards synced</span><span>{s.boards_synced ? fmtTime(s.boards_synced) : "never"}</span>
          </div>
          <div className="small muted mt">Last deployment log</div>
          <pre className="json">{s.deploy_log}</pre>
        </Card>
        <Card title="Diagnosis" actions={<Mode mode={dx.mode} />}>
          <p><b>Root cause:</b> {dx.root_cause}</p>
          <p className="small">{dx.explanation}</p>
          <table><tbody>{dx.findings.map((f, i) => (
            <tr key={i}><td className="small"><code>{f.signal}</code></td><td className="small">{f.cause}<div className="muted">{f.fix ? `Fix: ${f.fix}` : `Manual: ${f.manual}`}</div></td></tr>))}</tbody></table>
          <h4 className="mt2">Proposed fixes</h4>
          {dx.proposed_fixes.length === 0 && <p className="muted small">No automatic fix needed.</p>}
          {dx.proposed_fixes.map((f) => (
            <div key={f.action} className="spread mt">
              <div><b>{f.label}</b><div className="small muted">Risk {f.risk} · rollback: {f.rollback}</div></div>
              <Button kind="primary" disabled={!me.permissions.includes("ops_apply")} onClick={async () => { setRes(await api.post("/admin/health/fix", { action: f.action })); reload(); }}>Approve & apply</Button>
            </div>
          ))}
          {res && <Alert tone="ok">Applied {res.action}. Missing tables before: {res.before.missing_tables.length}, after: {res.after.missing_tables.length}.</Alert>}
        </Card>
      </div>
    </>
  );
}
