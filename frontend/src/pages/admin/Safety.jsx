import { Fragment, useState } from "react";
import { api } from "../../api";
import { Badge, Card, Tabs, fmtTime, useLoad } from "../../ui";

const KINDS = [["", "All"], ["agent", "Agents"], ["llm", "AI calls"], ["tool", "Tool calls"], ["human", "People"], ["guardrail", "Guardrails"]];

export default function Safety() {
  const [d] = useLoad(() => api.get("/admin/safety"));
  const [kind, setKind] = useState("");
  const [rows] = useLoad(() => api.get(`/admin/audit?kind=${kind}`), [kind]);
  const [open, setOpen] = useState(null);
  return (
    <>
      <div className="page-head"><div><h1>Audit & safety</h1><div className="muted">Evaluation checks, risk controls, permissions and the full audit log.</div></div></div>
      {d && (
        <div className="grid2">
          <Card title="Evaluation checks" subtitle={`${d.evals.filter((e) => e.passed).length} of ${d.evals.length} passing (run on every page load against the live rules)`}>
            {d.evals.map((e) => (
              <div key={e.case} className="spread small" style={{ padding: "5px 0", borderBottom: "1px solid var(--line)" }}>
                <span>{e.passed ? <b style={{ color: "var(--green)" }}>✓</b> : <b style={{ color: "var(--red)" }}>✗</b>} {e.case}</span>
                {!e.passed && <span className="muted">got {JSON.stringify(e.got)}</span>}
              </div>
            ))}
          </Card>
          <Card title="Risks and controls">
            {d.risks.map((r) => (
              <div key={r.risk} style={{ padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
                <div className="row"><Badge value={r.severity === "High" ? "FAIL" : "PENDING"} label={r.severity} /><b className="small">{r.risk}</b></div>
                <div className="small muted">{r.control}</div>
              </div>
            ))}
          </Card>
        </div>
      )}
      {d && (
        <Card title="Who can do what (enforced by the API)">
          <table><tbody>{Object.entries(d.permissions).map(([role, p]) => <tr key={role}><td><b>{role}</b></td><td className="small">{p.join(", ").replace(/_/g, " ")}</td></tr>)}</tbody></table>
        </Card>
      )}
      <Card title="Audit log" subtitle="Append-only record of every agent step, AI call, tool call and human decision">
        <Tabs tabs={KINDS} value={kind} onChange={setKind} />
        <table><tbody>{(rows || []).map((r) => (
          <Fragment key={r.id}>
            <tr className="click" onClick={() => setOpen(open === r.id ? null : r.id)}>
              <td className="small muted nowrap">{fmtTime(r.ts)}</td><td><Badge value={r.kind} label={r.kind} tone="grey" /></td>
              <td className="small"><b>{r.actor}</b></td><td className="small">{r.action}</td><td className="small muted">{r.record_id}</td><td className="small muted">{r.run_id}</td>
            </tr>
            {open === r.id && <tr><td colSpan={6}><pre className="json">{JSON.stringify(r.detail, null, 2)}</pre></td></tr>}
          </Fragment>))}</tbody></table>
      </Card>
    </>
  );
}
