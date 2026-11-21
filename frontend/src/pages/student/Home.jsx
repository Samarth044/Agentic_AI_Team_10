import { api } from "../../api";
import { AgentWorking, OppCard } from "../../components/Common";
import { Badge, Card, Chips, Empty, Stat, useLoad, usePoll } from "../../ui";

const NEXT = {
  SAVED: "Apply on the company site, then mark it applied", APPLIED: "Waiting to hear back from the company",
  INTERVIEW: "Prepare for your interview", OFFERED: "Approval Agent is checking your offer",
  NOC_PENDING: "Waiting for your coordinator to approve the NOC", NOC_CHANGES: "Your coordinator asked for changes",
  ONGOING: "Submit this week's log", COMPLETED: "Waiting for your mentor's rating",
  GRADE_PENDING: "Grade waiting for coordinator sign-off", GRADED: "Done",
};

export default function StudentHome({ me, refresh }) {
  const s = me.student;
  const working = ["parsing", "matching", "queued"].includes(s.agent_status);
  const [list, reloadList] = useLoad(() => api.get("/internships"), [s.matched_at]);
  const [ins, reloadIns] = useLoad(() => api.get("/insights"), [s.matched_at]);
  const [recs] = useLoad(() => api.get("/records"));
  usePoll(() => { refresh(); reloadList(); reloadIns(); }, working, 2500);
  const prof = s.resume_profile;
  const active = (recs || []).filter((r) => !["GRADED", "NOT_SELECTED", "WITHDRAWN", "NOC_REJECTED"].includes(r.stage));

  return (
    <>
      <div className="page-head">
        <div><h1>Hi {s.name.split(" ")[0]} 👋</h1><div className="muted">{prof?.headline || `${s.department} · Semester ${s.semester}`}</div></div>
        <a className="btn primary" href="#/internships">Browse internships</a>
      </div>
      <AgentWorking status={s.agent_status} message={s.agent_message} />
      {!prof && !working && (
        <div className="banner">
          <div><h2>Upload your resume to get matched</h2><div className="muted">Our agents read it, pick out your skills and projects, and rank every internship for you.</div></div>
          <a className="btn lg" href="#/profile">Upload resume</a>
        </div>
      )}
      <div className="stats">
        <Stat label="Internships matched" value={ins?.matches ?? "-"} tone="blue" hint={`${ins?.strong ?? 0} strong (70%+)`} />
        <Stat label="You are eligible for" value={ins?.eligible ?? "-"} tone="green" />
        <Stat label="Applications" value={ins?.applications ?? 0} tone="violet" />
        <Stat label="Ongoing internships" value={ins?.active ?? 0} />
      </div>
      <div className="split">
        <div>
          <Card title="Top matches for you" actions={<a href="#/internships">See all</a>}>
            {list?.items?.length ? list.items.slice(0, 4).map((o) => <OppCard key={o.id} o={o} />)
              : <Empty title="No matches yet">{prof ? "Agents are still matching, or no postings fit yet." : "Upload your resume to see matches."}</Empty>}
          </Card>
        </div>
        <div>
          <Card title="My applications" actions={<a href="#/applications">All</a>}>
            {active.length === 0 && <p className="muted small">No active applications. Open a match and click Apply.</p>}
            {active.slice(0, 5).map((r) => (
              <a key={r.id} href={`#/records/${r.id}`} style={{ display: "block", color: "inherit", padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
                <div className="spread"><b>{r.company}</b><Badge value={r.stage} /></div>
                <div className="small muted">{NEXT[r.stage]}</div>
              </a>
            ))}
          </Card>
          <Card title="Skills to grow" subtitle="Missing most often in your good matches">
            {ins?.gaps?.length ? ins.gaps.slice(0, 6).map((g) => (
              <div key={g.skill} className="spread" style={{ padding: "5px 0" }}>
                <span className="chip red">{g.skill}</span><span className="small muted">needed by {g.count} internship{g.count > 1 ? "s" : ""}</span>
              </div>
            )) : <p className="muted small">No gaps yet.</p>}
          </Card>
          {prof && (
            <Card title="Your profile" actions={<a href="#/profile">Edit</a>}>
              <p className="small">{prof.summary}</p>
              <Chips items={(s.skills || []).slice(0, 14)} />
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
