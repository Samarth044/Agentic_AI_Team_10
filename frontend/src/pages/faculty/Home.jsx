import { api } from "../../api";
import { Logo } from "../../components/Common";
import { Badge, Card, Empty, Stat, useLoad } from "../../ui";

export function QueueTable({ rows }) {
  if (!rows?.length) return <Empty icon="✓" title="Nothing waiting">You're all caught up.</Empty>;
  return (
    <table><tbody>
      {rows.map((r) => (
        <tr key={r.id} className="click" onClick={() => { window.location.hash = `#/records/${r.id}`; }}>
          <td style={{ width: 50 }}><Logo name={r.company} size={34} /></td>
          <td><b>{r.student}</b> <span className="small muted">{r.usn}</span><div className="small">{r.title} · {r.company}</div></td>
          <td><Badge value={r.stage} /></td>
          <td className="small" style={{ maxWidth: 340 }}>{r.recommendation && <span style={{ color: r.recommendation.startsWith("APPROVE") ? "var(--green)" : "var(--amber)" }}>{r.recommendation}</span>}</td>
        </tr>
      ))}
    </tbody></table>
  );
}

export default function FacultyHome({ me }) {
  const [d] = useLoad(() => api.get("/faculty/overview"));
  if (!d) return <p>Loading…</p>;
  return (
    <>
      <div className="page-head"><div><h1>Good day, {me.user.name.split(" ").slice(-1)[0]}</h1><div className="muted">{me.user.title}</div></div>
        <a className="btn primary" href="#/opportunities">Post an internship</a></div>
      <div className="stats">
        <Stat label="Waiting for your decision" value={d.counts.pending} tone="violet" />
        <Stat label="Students" value={d.counts.students} tone="blue" />
        <Stat label="Internships ongoing" value={d.counts.ongoing} tone="green" />
        <Stat label="Graded" value={d.counts.graded} />
      </div>
      <Card title="Waiting for your decision" actions={<a href="#/approvals">Open queue</a>}><QueueTable rows={d.pending} /></Card>
      <div className="grid2">
        <Card title="Interns needing attention" subtitle="Flagged by the Progress Agent">
          {d.at_risk.length === 0 ? <p className="muted small">All ongoing interns are on track.</p> : d.at_risk.map((r) => (
            <a key={r.id} href={`#/records/${r.id}`} className="spread" style={{ padding: "8px 0", color: "inherit", borderBottom: "1px solid var(--line)" }}>
              <span><b>{r.student}</b><div className="small muted">{r.company}</div></span><Badge value={r.health} /></a>
          ))}
        </Card>
        <Card title="Students" actions={<a href="#/students">All students</a>}>
          <table><tbody>{d.students.slice(0, 6).map((s) => (
            <tr key={s.id} className="click" onClick={() => { window.location.hash = `#/students/${s.id}`; }}>
              <td><b>{s.name}</b><div className="small muted">{s.department} · sem {s.semester} · CGPA {s.cgpa ?? "-"}</div></td>
              <td className="small">{s.eligible_matches} good matches</td><td className="small">{s.applications} applications</td>
            </tr>))}</tbody></table>
        </Card>
      </div>
    </>
  );
}
