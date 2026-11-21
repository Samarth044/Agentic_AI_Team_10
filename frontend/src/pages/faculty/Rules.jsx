import { useState } from "react";
import { api } from "../../api";
import { Alert, Badge, Button, Card, Mode, fmtDate, useLoad } from "../../ui";

const EXAMPLES = ["Minimum attendance of 80% is required", "No more than 2 active backlogs allowed", "Students need a CGPA of at least 6.5"];

export default function Rules() {
  const [d, reload] = useLoad(() => api.get("/rules"));
  const [req, setReq] = useState("");
  const [prop, setProp] = useState(null);
  const [msg, setMsg] = useState(["", ""]);
  const propose = async () => { setMsg(["", ""]); setProp(null); try { setProp(await api.post("/rules/propose", { requirement: req })); } catch (e) { setMsg(["error", e.message]); } };
  const publish = async () => {
    try {
      const r = await api.post("/rules/publish", { spec: prop.spec });
      setMsg(["ok", `Published "${r.rule.name}" (v${r.rule.version}). Eligibility re-checked for ${r.rechecked} student-internship pairs.`]);
      setProp(null); setReq(""); reload();
    } catch (e) { setMsg(["error", e.message]); }
  };
  const rollback = async (key) => {
    const r = await api.post(`/rules/${key}/rollback`);
    setMsg(["ok", `Rolled back. Active version: ${r.active_version ?? "none"}. Re-checked ${r.rechecked} pairs.`]);
    reload();
  };
  if (!d) return <p>Loading…</p>;
  const stage = (n) => prop?.stages.find((s) => s.stage === n);
  return (
    <>
      <div className="page-head"><div><h1>Eligibility rules</h1><div className="muted">College policy and employer criteria applied to every match. Every change is versioned and can be rolled back.</div></div></div>
      <Alert tone={msg[0]}>{msg[1]}</Alert>
      <Card title="Add a college rule in plain English" subtitle="The Policy Agent writes the rule, tests it, and shows who it would affect before you publish.">
        <div className="row"><input value={req} onChange={(e) => setReq(e.target.value)} placeholder="e.g. Minimum attendance of 80% is required" style={{ flex: 1 }} />
          <Button kind="primary" onClick={propose} disabled={!req.trim()}>Draft rule</Button></div>
        <div className="row mt small">{EXAMPLES.map((e) => <button key={e} className="btn" onClick={() => setReq(e)}>{e}</button>)}</div>
        {prop && (
          <div className="mt2">
            {!prop.ok && <Alert>{prop.error || "The generated tests failed; the rule cannot be published."}</Alert>}
            <div className="grid3">
              <div><h4>1. Requirement <Mode mode={stage("Requirement")?.mode} /></h4><p className="small">{stage("Requirement")?.output.user_story}</p>
                <ul className="small">{(stage("Requirement")?.output.acceptance_criteria || []).map((a, i) => <li key={i}>{a}</li>)}</ul></div>
              <div><h4>2. Rule & tests</h4><p><b>{prop.rule}</b></p>
                {(stage("Test")?.output || []).map((t) => <div key={t.case} className="small">{t.passed ? "✓" : "✗"} {t.case} → {t.got} (expected {t.expect})</div>)}</div>
              <div><h4>3. Who it affects</h4>
                {(stage("Impact preview")?.output || []).map((i) => <div key={i.student} className="spread small"><span>{i.student} ({i.value ?? "-"})</span><Badge value={i.result} /></div>)}</div>
            </div>
            <div className="row mt"><Button kind="green" disabled={!prop.ok} onClick={publish}>Publish rule</Button><button className="btn" onClick={() => setProp(null)}>Discard</button></div>
          </div>
        )}
      </Card>
      <Card title="Rules and versions">
        <table><thead><tr><th>Rule</th><th>Applies</th><th>Version</th><th>Status</th><th>Created</th><th></th></tr></thead>
          <tbody>{d.all.map((r) => (
            <tr key={r.id}><td><b>{r.name}</b></td><td className="small">{r.scope === "institution" ? "College policy" : "Employer's stated criterion"}</td>
              <td>v{r.version}</td><td><Badge value={r.active ? "APPROVED" : "WITHDRAWN"} label={r.active ? "Active" : "Inactive"} /></td>
              <td className="small muted">{r.created_by} · {fmtDate(r.created_at)}</td>
              <td>{r.active && r.created_by !== "seed" ? <Button kind="red" onClick={() => rollback(r.rule_key)}>Roll back</Button> : null}</td></tr>))}</tbody></table>
      </Card>
    </>
  );
}
