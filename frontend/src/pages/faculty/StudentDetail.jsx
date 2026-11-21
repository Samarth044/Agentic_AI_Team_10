import { api } from "../../api";
import { Badge, Card, Chips, useLoad } from "../../ui";

export default function StudentDetail({ id }) {
  const [d, , err] = useLoad(() => api.get(`/students/${id}`), [id]);
  if (!d) return err ? <div className="alert error">{err}</div> : <p>Loading…</p>;
  const s = d.student, p = s.resume_profile || {};
  return (
    <>
      <a href="#/students">← Students</a>
      <div className="page-head mt"><div><h1>{s.name}</h1><div className="muted">{s.usn} · {s.department} · semester {s.semester} · {s.email}</div></div></div>
      <div className="split">
        <div>
          <Card title="Applications & internships">
            {d.records.length === 0 && <p className="muted small">No applications yet.</p>}
            <table><tbody>{d.records.map((r) => (
              <tr key={r.id} className="click" onClick={() => { window.location.hash = `#/records/${r.id}`; }}>
                <td><b>{r.title}</b><div className="small muted">{r.company}</div></td><td><Badge value={r.stage} /></td><td>{r.health && <Badge value={r.health} />}</td>
              </tr>))}</tbody></table>
          </Card>
          <Card title="Top matches">
            <table><tbody>{d.matches.map((m) => (
              <tr key={m.id}><td><b>{m.title}</b><div className="small muted">{m.company}</div></td><td className="nowrap"><b>{Math.round(m.score)}%</b></td>
                <td><Badge value={m.eligibility.status} /></td><td><Chips items={m.missing.slice(0, 3)} tone="red" empty="no gaps" /></td></tr>))}</tbody></table>
          </Card>
        </div>
        <div>
          <Card title="Academic record">
            <div className="kv"><span className="k">CGPA</span><span>{s.cgpa ?? "-"}</span><span className="k">Attendance</span><span>{s.attendance_pct ?? "-"}%</span>
              <span className="k">Active backlogs</span><span>{s.active_backlogs ?? "-"}</span><span className="k">Interests</span><span>{s.preferred_domains || "-"}</span></div>
          </Card>
          <Card title="Resume summary">
            <p className="small">{p.summary || "No resume uploaded yet."}</p>
            <Chips items={s.skills} />
          </Card>
          <Card title="Skill gaps"><Chips items={d.gaps.map((g) => `${g.skill} (${g.count})`)} tone="red" empty="none" /></Card>
        </div>
      </div>
    </>
  );
}
