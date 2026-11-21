import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { fmtTime } from "../ui";

// Turns one audit event into a readable line for the live log.
export function describe(e) {
  const d = e.detail || {};
  const ms = d.ms != null ? ` · ${d.ms >= 1000 ? `${(d.ms / 1000).toFixed(1)}s` : `${d.ms}ms`}` : "";
  switch (e.kind) {
    case "run":
      if (e.action === "run_started") return ["▶", "run", `Run started: ${d.goal}`, `channel: ${d.channel} · by ${d.actor}`];
      if (e.action === "run_named") return ["▶", "run", `Run: ${d.goal}`, `channel: ${d.channel}`];
      if (e.action === "run_failed") return ["✗", "bad", "Run failed", d.error];
      return ["■", "run", `Run finished (${d.status})${ms}`, ""];
    case "loop":
      return ["◆", "loop", `${e.actor} · ${e.action}`, d.text];
    case "agent":
      if (e.action === "called") return ["🤖", "agent", `${e.actor} called`, [d.method && `task: ${d.method.replace(/_/g, " ")}`, d.skill && `skill: ${d.skill}`, d.tools?.length && `tools: ${d.tools.join(", ")}`].filter(Boolean).join(" · ")];
      if (e.action === "finished") return ["✓", "ok", `${e.actor} finished${ms}`, d.result];
      if (e.action === "failed") return ["✗", "bad", `${e.actor} failed`, d.error];
      if (e.action === "skill_loaded") return ["📘", "skill", `${e.actor} loaded skill ${d.skill}`, `${d.chars} characters of SKILL.md added to the prompt`];
      return ["•", "agent", `${e.actor}: ${e.action.replace(/_/g, " ")}`, summarize(d)];
    case "tool":
      if (d.transport === undefined) return ["🔧", "tool", `${e.actor} used function ${e.action}`, "function calling"];
      return [d.ok === false ? "✗" : "🔧", d.ok === false ? "bad" : "tool", `${e.actor} → tool ${e.action}`, `via ${d.transport.toUpperCase()}${ms}${d.ok === false ? ` · ${d.error}` : ""}`];
    case "llm":
      if (e.action === "model_call") return ["🧠", "llm", `${e.actor} asked the AI model`, `${d.model}${ms}${d.tokens ? ` · ${d.tokens} tokens` : ""}${d.function_calls?.length ? ` · wants: ${d.function_calls.join(", ")}` : ""}`];
      return ["🧠", "warn", `${e.actor}: AI unavailable, used rule-based fallback`, d.error || d.reason];
    case "memory":
      if (e.action === "recalled") return ["💾", "mem", "Memory recalled", `${d.returned} of ${d.stored} entries for "${d.query}"`];
      return ["💾", "mem", "Memory saved", `[${d.kind}] ${d.content}`];
    case "human":
      return ["👤", "human", `${e.actor}: ${e.action.replace(/_/g, " ")}`, summarize(d)];
    case "guardrail":
      return ["🛡", "bad", `Guardrail: ${e.action.replace(/_/g, " ")}`, summarize(d)];
    default:
      return ["•", "", `${e.actor}: ${e.action}`, summarize(d)];
  }
}

const summarize = (d) => Object.entries(d || {}).filter(([k, v]) => !["prompt", "response"].includes(k) && v !== null && v !== "" && typeof v !== "object")
  .slice(0, 4).map(([k, v]) => `${k}: ${String(v).slice(0, 60)}`).join(" · ");

export function Feed({ events, onRun, showPrompts }) {
  let lastRun = null;
  return (
    <div className="feed">
      {events.map((e) => {
        const [icon, tone, title, sub] = describe(e);
        const head = e.run_id !== lastRun;
        lastRun = e.run_id;
        return (
          <div key={e.id}>
            {head && <div className="feed-run" onClick={() => onRun?.(e.run_id)}><b>{e.run_id}</b> · {e.goal}</div>}
            <div className={`ev ${tone}`}>
              <span className="ev-ico">{icon}</span>
              <div className="ev-body">
                <div className="ev-title">{title}</div>
                {sub && <div className="ev-sub">{sub}</div>}
                {showPrompts && e.detail?.prompt && (
                  <details><summary>prompt & response</summary><pre className="json">{e.detail.prompt}{"\n\n--- response ---\n\n"}{e.detail.response}</pre></details>
                )}
              </div>
              <span className="ev-time">{fmtTime(e.ts).split(", ").pop()}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Polls /api/activity and keeps the newest events.
export function useActivity(active, max = 250) {
  const [events, setEvents] = useState([]);
  const last = useRef(0);
  useEffect(() => {
    if (!active) return;
    let stop = false;
    const tick = async () => {
      try {
        const rows = await api.get(`/activity?after=${last.current}&limit=500`);
        if (rows.length && !stop) {
          last.current = rows[rows.length - 1].id;
          setEvents((ev) => [...ev, ...rows].slice(-max));
        }
      } catch { /* logged out */ }
    };
    tick();
    const t = setInterval(tick, 1500);
    return () => { stop = true; clearInterval(t); };
  }, [active, max]);
  return events;
}

export function ActivityDrawer({ onClose }) {
  const events = useActivity(true, 200);
  const body = useRef(null);
  const [follow, setFollow] = useState(true);
  useEffect(() => { if (follow) body.current?.scrollTo(0, 1e7); }, [events, follow]);
  const agents = new Set(events.filter((e) => e.kind === "agent" && e.action === "called").map((e) => e.actor));
  return (
    <div className="drawer">
      <div className="drawer-head">
        <div><b>⚡ Live agent activity</b><div className="small" style={{ opacity: .8 }}>{agents.size} agent(s) seen · updates every 1.5s</div></div>
        <div className="row">
          <label className="check-row small" style={{ color: "#fff" }}><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> follow</label>
          <a className="small" style={{ color: "#fff" }} href="#/activity" onClick={onClose}>full log</a>
          <button className="x" style={{ color: "#fff" }} onClick={onClose}>×</button>
        </div>
      </div>
      <div className="drawer-body" ref={body}>
        {events.length === 0 ? <p className="muted small" style={{ padding: 14 }}>Nothing yet. Do something in the portal (upload a resume, apply, approve) and watch the agents work here.</p>
          : <Feed events={events} />}
      </div>
    </div>
  );
}
