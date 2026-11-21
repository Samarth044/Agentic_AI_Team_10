import { api } from "../../api";
import { Logo } from "../../components/Common";
import { Badge, Card, Empty, Stat, useLoad } from "../../ui";

export default function MentorHome({ me }) {
  const [rows] = useLoad(() => api.get("/mentor/overview"));
  if (!rows) return <p>Loading…</p>;
  const toVerify = rows.reduce((a, r) => a + r.unverified_logs, 0);
  return (
    <>
      <div className="page-head"><div><h1>My interns</h1><div className="muted">{me.user.title}</div></div></div>
      <div className="stats">
        <Stat label="Interns" value={rows.length} tone="blue" />
        <Stat label="Logs to verify" value={toVerify} tone="violet" />
        <Stat label="Ratings to give" value={rows.filter((r) => r.stage === "COMPLETED" && r.needs_rating).length} tone="amber" />
        <Stat label="Flagged at risk" value={rows.filter((r) => ["AT_RISK", "DELAYED"].includes(r.health)).length} />
      </div>
      <Card>
        {rows.length === 0 ? <Empty title="No interns assigned yet">The coordinator assigns you when approving a student's NOC.</Empty> : (
          <table><tbody>{rows.map((r) => (
            <tr key={r.id} className="click" onClick={() => { window.location.hash = `#/records/${r.id}`; }}>
              <td style={{ width: 50 }}><Logo name={r.student} size={36} /></td>
              <td><b>{r.student}</b><div className="small muted">{r.title} · {r.company}</div></td>
              <td><Badge value={r.stage} /></td>
              <td>{r.health && <Badge value={r.health} />}</td>
              <td className="small">{r.unverified_logs > 0 ? <b style={{ color: "var(--violet)" }}>{r.unverified_logs} log(s) to verify</b> : "All logs verified"}
                {r.stage === "COMPLETED" && r.needs_rating && <div style={{ color: "var(--amber)" }}>Final rating needed</div>}</td>
            </tr>))}</tbody></table>
        )}
      </Card>
    </>
  );
}
