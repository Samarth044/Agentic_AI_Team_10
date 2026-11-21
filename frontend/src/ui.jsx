import { useCallback, useEffect, useRef, useState } from "react";

export const STAGES = {
  SAVED: ["Preparing", "blue"], APPLIED: ["Applied", "blue"], INTERVIEW: ["Interviewing", "blue"],
  OFFERED: ["Offer received", "violet"], NOC_PENDING: ["NOC pending", "violet"],
  NOC_CHANGES: ["NOC: changes needed", "amber"], ONGOING: ["Ongoing", "green"],
  COMPLETED: ["Report submitted", "violet"], GRADE_PENDING: ["Grade pending", "violet"],
  GRADE_CHANGES: ["Re-evaluation", "amber"], GRADED: ["Graded", "green"],
  NOT_SELECTED: ["Not selected", "grey"], WITHDRAWN: ["Withdrawn", "grey"], NOC_REJECTED: ["NOC rejected", "red"],
};
const TONES = {
  ELIGIBLE: ["Eligible", "green"], NOT_ELIGIBLE: ["Not eligible", "red"], ON_TRACK: ["On track", "green"],
  AT_RISK: ["At risk", "amber"], DELAYED: ["Delayed", "red"], PASS: ["Pass", "green"], FAIL: ["Fail", "red"],
  NOT_STATED: ["Not stated", "grey"], PENDING: ["Pending", "violet"], APPROVED: ["Approved", "green"],
  REJECTED: ["Rejected", "red"], CHANGES_REQUESTED: ["Changes requested", "amber"],
  APPLY: ["Apply", "green"], MAYBE: ["Maybe", "amber"], SKIP: ["Skip", "red"],
  DRAFT: ["Draft", "violet"], FINAL: ["Final", "green"],
};

export function Badge({ value, label, tone }) {
  if (!value && !label) return null;
  const [l, t] = STAGES[value] || TONES[value] || [value, "blue"];
  return <span className={`badge ${tone || t}`}>{label || l}</span>;
}

export function Ring({ value, size = 54 }) {
  const v = Math.round(value || 0);
  const tone = v >= 70 ? "#1f8a4c" : v >= 50 ? "#c27c0e" : "#c53030";
  const r = size / 2 - 5, c = 2 * Math.PI * r;
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#e9edf5" strokeWidth="5" fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={tone} strokeWidth="5" fill="none" strokeLinecap="round"
          strokeDasharray={`${(c * v) / 100} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </svg>
      <span style={{ color: tone }}>{v}%</span>
    </div>
  );
}

export function Chips({ items, tone = "", empty = "-" }) {
  if (!items?.length) return <span className="muted small">{empty}</span>;
  return <div className="chips">{items.map((s) => <span key={s} className={`chip ${tone}`}>{s}</span>)}</div>;
}

export function Card({ title, subtitle, actions, children, className = "" }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div><h3>{title}</h3>{subtitle && <div className="muted small">{subtitle}</div>}</div>
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, tone = "", hint }) {
  return (
    <div className={`stat ${tone}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="small muted">{hint}</div>}
    </div>
  );
}

export function Empty({ icon = "○", title, children }) {
  return <div className="empty"><div className="empty-icon">{icon}</div><b>{title}</b><div className="muted">{children}</div></div>;
}

export function useLoad(fn, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    setError("");
    return fn().then(setData).catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return [data, reload, error, setData];
}

export function usePoll(fn, active, ms = 2000) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => saved.current(), ms);
    return () => clearInterval(t);
  }, [active, ms]);
}

export function Button({ onClick, children, kind = "", disabled, type = "button" }) {
  const [busy, setBusy] = useState(false);
  return (
    <button type={type} className={`btn ${kind}`} disabled={busy || disabled}
      onClick={async (e) => {
        if (!onClick) return;
        setBusy(true);
        try { await onClick(e); } finally { setBusy(false); }
      }}>
      {busy ? <span className="spinner" /> : null}{children}
    </button>
  );
}

export function Field({ label, children, hint }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small className="muted">{hint}</small>}</label>;
}

export function Modal({ title, onClose, children, wide }) {
  return (
    <div className="modal-back" onClick={onClose}>
      <div className={`modal ${wide ? "wide" : ""}`} onClick={(e) => e.stopPropagation()}>
        <div className="spread"><h3>{title}</h3><button className="x" onClick={onClose}>×</button></div>
        <div className="mt">{children}</div>
      </div>
    </div>
  );
}

export function Alert({ children, tone = "error" }) {
  return children ? <div className={`alert ${tone}`}>{children}</div> : null;
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs">
      {tabs.map(([k, l]) => <button key={k} className={value === k ? "active" : ""} onClick={() => onChange(k)}>{l}</button>)}
    </div>
  );
}

export const fmtDate = (s) => (s ? new Date(s).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "-");
export const fmtTime = (s) => (s ? new Date(s).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "-");
export const pct = (v) => `${Math.round(v || 0)}%`;

export function Mode({ mode }) {
  if (!mode) return null;
  const on = String(mode).startsWith("llm");
  return <span className={`mode ${on ? "on" : ""}`} title={on ? "Written by the AI agent" : "AI unavailable: rule-based fallback"}>{on ? "AI" : "offline"}</span>;
}
