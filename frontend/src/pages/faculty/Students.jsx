import { useState } from "react";
import { api } from "../../api";
import { Badge, Card, useLoad } from "../../ui";

export default function Students() {
  const [d] = useLoad(() => api.get("/faculty/overview"));
  const [q, setQ] = useState("");
  if (!d) return <p>Loading…</p>;
  const rows = d.students.filter((s) => `${s.name} ${s.usn} ${s.department}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <div className="page-head"><div><h1>Students</h1><div className="muted">{d.students.length} students assigned to you</div></div>
        <input type="search" placeholder="Search name, USN, branch" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 260 }} /></div>
      <Card>
        <table>
          <thead><tr><th>Student</th><th>Academics</th><th>Resume</th><th>Good matches</th><th>Applications</th><th>Status</th></tr></thead>
          <tbody>{rows.map((s) => (
            <tr key={s.id} className="click" onClick={() => { window.location.hash = `#/students/${s.id}`; }}>
              <td><b>{s.name}</b><div className="small muted">{s.usn}</div></td>
              <td className="small">{s.department} · sem {s.semester}<div className="muted">CGPA {s.cgpa ?? "-"} · attendance {s.attendance_pct ?? "-"}%</div></td>
              <td>{s.resume ? <Badge value="APPROVED" label={`${s.skills} skills`} /> : <Badge value="PENDING" label="No resume" />}</td>
              <td>{s.eligible_matches}</td>
              <td>{s.applications}{s.ongoing ? <span className="small muted"> · {s.ongoing} ongoing</span> : null}</td>
              <td>{s.at_risk ? <Badge value="AT_RISK" /> : <span className="small muted">-</span>}</td>
            </tr>))}</tbody>
        </table>
      </Card>
    </>
  );
}
