import { Badge, Chips, Ring } from "../ui";

const COLORS = ["#2f5bea", "#6a4cf5", "#1f8a4c", "#c27c0e", "#c53030", "#0e7490", "#be185d", "#4d7c0f"];
export function Logo({ name, size = 44 }) {
  const c = COLORS[[...(name || "?")].reduce((a, ch) => a + ch.charCodeAt(0), 0) % COLORS.length];
  return <div className="logo" style={{ background: c, width: size, height: size }}>{(name || "?")[0]}</div>;
}

export function AgentWorking({ status, message }) {
  if (!["parsing", "matching", "queued"].includes(status)) return null;
  return <div className="working"><span className="spinner" />{message || "Agents are working…"}</div>;
}

export function OppCard({ o }) {
  return (
    <div className="opp" onClick={() => { window.location.hash = `#/internships/${o.id}`; }}>
      <Ring value={o.score} />
      <div>
        <div className="row"><h3>{o.title}</h3>{o.record && <Badge value={o.record.stage} />}</div>
        <div className="meta">{o.company} · {o.location} ({o.mode}) · {o.duration_weeks ? `${o.duration_weeks} weeks` : "duration not stated"} · {o.stipend}</div>
        {o.why && <div className="why">{o.why}</div>}
        <div className="row mt" style={{ gap: 14, alignItems: "flex-start" }}>
          <div><div className="small muted">You have</div><Chips items={o.have?.slice(0, 6)} tone="green" empty="none listed" /></div>
          <div><div className="small muted">You lack</div><Chips items={o.missing?.slice(0, 5)} tone="red" empty="nothing" /></div>
        </div>
      </div>
      <div className="right">
        <Badge value={o.eligibility} />
        {o.deadline && <div className="small muted mt">Apply by {o.deadline}</div>}
        <div className="small muted">{o.source === "campus" || o.source === "faculty" ? "Posted by college" : `via ${o.source}`}</div>
      </div>
    </div>
  );
}
