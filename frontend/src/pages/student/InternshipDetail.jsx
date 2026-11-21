import { useState } from "react";
import { api } from "../../api";
import { Logo } from "../../components/Common";
import { Alert, Badge, Button, Card, Chips, Mode, Ring, useLoad } from "../../ui";

export default function InternshipDetail({ id }) {
  const [d, reload, err] = useLoad(() => api.get(`/internships/${id}`), [id]);
  const [panel, setPanel] = useState(null);
  const [research, setResearch] = useState(null);
  const [error, setError] = useState("");
  if (!d) return err ? <Alert>{err}</Alert> : <p>Loading…</p>;
  const { opportunity: o, match: m, record } = d;
  const rs = research || d.research;
  const el = m.eligibility;
  const pv = panel || m.panel;

  const start = async () => {
    setError("");
    try {
      const r = await api.post(`/internships/${id}/apply`);
      window.location.hash = `#/records/${r.record_id}`;
    } catch (e) { setError(e.message); }
  };

  return (
    <>
      <a href="#/internships">← All internships</a>
      <Card className="mt">
        <div className="spread" style={{ alignItems: "flex-start" }}>
          <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
            <Logo name={o.company} size={56} />
            <div>
              <h1>{o.title}</h1>
              <div className="muted">{o.company} · {o.location} ({o.mode}) · {o.duration_weeks ? `${o.duration_weeks} weeks` : "duration not stated"} · {o.stipend}</div>
              <div className="row mt"><Badge value={el.status} />{o.deadline && <span className="small muted">Apply by {o.deadline}</span>}
                <span className="small muted">{["campus", "faculty"].includes(o.source) ? "Posted by your college" : `From ${o.source}`}</span></div>
            </div>
          </div>
          <Ring value={m.score} size={76} />
        </div>
        <Alert>{error}</Alert>
        <div className="row mt">
          {record ? <a className="btn primary lg" href={`#/records/${record.id}`}>View my application →</a>
            : el.status === "ELIGIBLE" ? <Button kind="primary lg" onClick={start}>Apply</Button>
            : <span className="badge red">You can't apply: {el.shortfalls.join("; ")}</span>}
          {el.status === "ELIGIBLE" && <a className="btn lg" href={o.url} target="_blank" rel="noreferrer">Company page ↗</a>}
          {!record && el.status === "ELIGIBLE" && <span className="small muted">Apply prepares your cover letter and starts tracking this application.</span>}
        </div>
      </Card>

      <div className="grid2">
        <Card title="Why this fits you" actions={<Mode mode={m.mode} />}>
          <p>{m.why}</p>
          {m.highlight && <p className="small"><b>Highlight in your application:</b> {m.highlight}</p>}
          <div className="kv mt">
            <span className="k">Skills fit</span><div className="bar"><div style={{ width: `${m.skills_fit}%` }} /></div>
            <span className="k">Role fit</span><div className="bar"><div style={{ width: `${m.role_fit}%` }} /></div>
            <span className="k">Location fit</span><div className="bar"><div style={{ width: `${m.pref_fit}%` }} /></div>
          </div>
        </Card>
        <Card title="Skills">
          <div className="small muted">You have</div><Chips items={m.have} tone="green" empty="none of the listed skills yet" />
          <div className="small muted mt">You lack</div><Chips items={m.missing} tone="red" empty="nothing, you cover every listed skill" />
          {m.improve && <Alert tone="info"><b>How to close the gap:</b> {m.improve}</Alert>}
        </Card>
      </div>

      <div className="grid2">
        <Card title="Eligibility check" subtitle={el.summary}>
          <table><tbody>
            {el.checks.map((c) => <tr key={c.rule}><td style={{ width: 100 }}><Badge value={c.status} /></td><td>{c.message}<div className="small muted">{c.name}</div></td></tr>)}
          </tbody></table>
        </Card>
        <Card title="About the internship">
          <p style={{ whiteSpace: "pre-wrap" }}>{o.description}</p>
          {o.required_skills?.length > 0 && <><div className="small muted mt">Required skills</div><Chips items={o.required_skills} /></>}
        </Card>
      </div>

      <div className="grid2">
        <Card title="Company insights" subtitle="Researched from public sources and this portal's history"
          actions={<><Mode mode={rs?.mode} /><Button onClick={async () => setResearch(await api.post("/research", { company: o.company, force: !!rs }))}>{rs ? "Refresh" : "Research company"}</Button></>}>
          {!rs ? <p className="muted small">The research agent checks public information and how past students did with this company, then writes a short briefing with sources.</p> : (
            <>
              <p>{rs.briefing}</p>
              {rs.recommendation && <Alert tone="info">{rs.recommendation}</Alert>}
              <details><summary className="small">Sources ({rs.evidence.length})</summary>
                <table className="mt"><tbody>{rs.evidence.map((e) => (
                  <tr key={e.id}><td><b>{e.id}</b></td><td className="small">{e.claim}</td>
                    <td className="small nowrap">{e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.source}</a> : e.source}</td>
                    <td><Badge value={e.confidence === "High" ? "PASS" : "PENDING"} label={e.confidence} /></td></tr>))}
                </tbody></table>
              </details>
            </>
          )}
        </Card>
        <Card title="Expert panel review" subtitle="Four reviewer agents assess this internship for you in parallel"
          actions={<Button onClick={async () => { setPanel(await api.post(`/internships/${id}/panel`)); reload(); }}>{pv ? "Review again" : "Get review"}</Button>}>
          {!pv ? <p className="muted small">Skills, academic, safety and career reviewers each give a verdict; disagreements are flagged and resolved.</p> : (
            <>
              <div className="spread"><h2><Badge value={pv.verdict} label={`Verdict: ${pv.verdict}`} /></h2><span className="small muted">avg score {pv.average}</span></div>
              <p className="small">{pv.resolution}</p>
              {pv.conflicts.map((c, i) => <Alert key={i} tone="warn">{c}</Alert>)}
              {pv.reviews.map((r) => (
                <div key={r.role} className="mt">
                  <div className="spread"><b>{r.role}</b><span className="row"><Badge value={r.verdict} label={`${r.verdict} · ${r.score}`} /><Mode mode={r.mode} /></span></div>
                  <ul className="small">{r.points.map((p, i) => <li key={i}>{p}</li>)}</ul>
                </div>
              ))}
            </>
          )}
        </Card>
      </div>
    </>
  );
}
