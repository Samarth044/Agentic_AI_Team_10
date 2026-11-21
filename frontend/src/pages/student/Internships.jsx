import { useState } from "react";
import { api } from "../../api";
import { AgentWorking, OppCard } from "../../components/Common";
import { Empty, useLoad, usePoll } from "../../ui";

export default function Internships({ me, refresh }) {
  const [q, setQ] = useState("");
  const [eligible, setEligible] = useState(false);
  const [remote, setRemote] = useState(false);
  const [min, setMin] = useState(0);
  const [data, reload] = useLoad(() => api.get(`/internships?q=${encodeURIComponent(q)}&eligible=${eligible}&remote=${remote}&min_score=${min}`),
    [q, eligible, remote, min, me.student.matched_at]);
  const working = ["parsing", "matching", "queued"].includes(me.student.agent_status);
  usePoll(() => { refresh(); reload(); }, working, 2500);
  return (
    <>
      <div className="page-head">
        <div><h1>Internships for you</h1>
          <div className="muted">{data ? `${data.items.length} shown of ${data.open_postings} open postings, ranked by how well they fit your resume` : "Loading…"}</div></div>
        <button className="btn" onClick={() => api.post("/profile/rematch").then(refresh)}>↻ Re-match</button>
      </div>
      <AgentWorking status={me.student.agent_status} message={me.student.agent_message} />
      <div className="filters">
        <input type="search" placeholder="Search title, company, city…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="check-row"><input type="checkbox" checked={eligible} onChange={(e) => setEligible(e.target.checked)} /> Eligible only</label>
        <label className="check-row"><input type="checkbox" checked={remote} onChange={(e) => setRemote(e.target.checked)} /> Remote only</label>
        <select value={min} onChange={(e) => setMin(Number(e.target.value))} style={{ width: 160 }}>
          <option value={0}>Any match</option><option value={50}>50%+ match</option><option value={70}>70%+ match</option>
        </select>
      </div>
      {data?.items?.map((o) => <OppCard key={o.id} o={o} />)}
      {data && data.items.length === 0 && (
        <Empty title="Nothing here yet">
          {me.student.resume_profile ? "Try clearing the filters." : <>Upload your resume on the <a href="#/profile">profile page</a> to get matched.</>}
        </Empty>
      )}
    </>
  );
}
