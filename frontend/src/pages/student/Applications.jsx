import { api } from "../../api";
import { Logo } from "../../components/Common";
import { Badge, Card, Empty, fmtDate, useLoad } from "../../ui";

const CLOSED = ["GRADED", "NOT_SELECTED", "WITHDRAWN", "NOC_REJECTED"];

export default function Applications() {
  const [rows] = useLoad(() => api.get("/records"));
  if (!rows) return <p>Loading…</p>;
  const active = rows.filter((r) => !CLOSED.includes(r.stage));
  const closed = rows.filter((r) => CLOSED.includes(r.stage));
  const table = (list) => (
    <table><tbody>
      {list.map((r) => (
        <tr key={r.id} className="click" onClick={() => { window.location.hash = `#/records/${r.id}`; }}>
          <td style={{ width: 54 }}><Logo name={r.company} size={36} /></td>
          <td><b>{r.title}</b><div className="small muted">{r.company} · {r.location}</div></td>
          <td><Badge value={r.stage} />{r.health && <div className="mt"><Badge value={r.health} /></div>}</td>
          <td className="small muted right">Updated {fmtDate(r.updated_at)}<div>{r.id}</div></td>
        </tr>
      ))}
    </tbody></table>
  );
  return (
    <>
      <div className="page-head"><div><h1>My applications</h1><div className="muted">Every application is one tracked record, from applying to your final grade.</div></div></div>
      <Card title={`Active (${active.length})`}>
        {active.length ? table(active) : <Empty title="No active applications">Find an internship and click <b>Apply</b>. <a href="#/internships">Browse internships</a></Empty>}
      </Card>
      {closed.length > 0 && <Card title={`Completed & closed (${closed.length})`}>{table(closed)}</Card>}
    </>
  );
}
