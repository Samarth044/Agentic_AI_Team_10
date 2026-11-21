import { useEffect, useRef, useState } from "react";
import { api } from "../api";

const SUGGEST = ["Which internships fit me best?", "What skills should I learn next?",
  "What is the attendance rule for an NOC?", "Status of my applications"];
const TOOL_LABEL = { search_internships: "searched matches", internship_details: "read posting",
  my_applications: "checked applications", skill_gaps: "analysed skill gaps", college_policy: "read policy",
  calculator: "calculated", remember: "saved to memory" };

// Minimal formatting for replies: **bold**, "- " bullets; table pipes become separators.
function Rich({ text }) {
  const lines = String(text || "").split("\n")
    .filter((l) => !/^\s*\|?\s*:?-{3,}/.test(l))
    .map((l) => l.trim().startsWith("|") ? l.split("|").map((c) => c.trim()).filter(Boolean).join(" · ") : l);
  return lines.map((l, i) => {
    const bullet = /^\s*[-*•]\s+/.test(l);
    const parts = l.replace(/^\s*[-*•]\s+/, "").replace(/^#+\s*/, "").split(/(\*\*[^*]+\*\*)/g)
      .map((p, j) => (p.startsWith("**") ? <b key={j}>{p.slice(2, -2)}</b> : p));
    return <div key={i} style={bullet ? { paddingLeft: 12, textIndent: -10 } : undefined}>{bullet ? "• " : ""}{parts}</div>;
  });
}

export default function Assistant() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const body = useRef(null);

  useEffect(() => { if (open) api.get("/assistant").then(setMsgs); }, [open]);
  useEffect(() => { body.current?.scrollTo(0, 1e6); }, [msgs, busy]);

  const send = async (m) => {
    const msg = (m ?? text).trim();
    if (!msg || busy) return;
    setText("");
    setMsgs((x) => [...x, { role: "user", content: msg }]);
    setBusy(true);
    try {
      const r = await api.post("/assistant", { message: msg });
      setMsgs((x) => [...x, { role: "assistant", content: r.reply, tools: r.tools.map((t) => t.tool) }]);
    } catch (e) {
      setMsgs((x) => [...x, { role: "assistant", content: `Sorry, something went wrong: ${e.message}` }]);
    } finally { setBusy(false); }
  };

  if (!open) return <button className="fab" onClick={() => setOpen(true)}>✦ Career assistant</button>;
  return (
    <div className="chat">
      <div className="chat-head">
        <div><b>Career assistant</b><div className="small" style={{ opacity: .85 }}>Knows your profile, matches and college policy</div></div>
        <div className="row">
          <button className="x" title="Clear chat" style={{ fontSize: 14 }} onClick={() => api.post("/assistant/clear").then(() => setMsgs([]))}>⟲</button>
          <button className="x" onClick={() => setOpen(false)}>×</button>
        </div>
      </div>
      <div className="chat-body" ref={body}>
        {msgs.length === 0 && <div className="msg assistant">Hi! Ask me about internships that fit you, skills to learn, your applications or the college's internship rules.</div>}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`} style={{ whiteSpace: "normal" }}>
            {m.role === "assistant" ? <Rich text={m.content} /> : m.content}
            {m.tools?.length > 0 && <div className="tools">{m.tools.map((t, j) => <span key={j}>{TOOL_LABEL[t] || t}</span>)}</div>}
          </div>
        ))}
        {busy && <div className="msg assistant"><span className="spinner" style={{ display: "inline-block" }} /> thinking…</div>}
      </div>
      {msgs.length < 2 && <div className="suggest">{SUGGEST.map((s) => <button key={s} onClick={() => send(s)}>{s}</button>)}</div>}
      <form className="chat-foot" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask anything about internships…" />
        <button className="btn primary" disabled={busy}>Send</button>
      </form>
    </div>
  );
}
