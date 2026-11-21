import { useCallback, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import { fmtTime } from "./ui";
import Assistant from "./components/Assistant";
import { ActivityDrawer } from "./components/Activity";
import ActivityPage from "./pages/Activity";
import Login from "./pages/Login";
import StudentHome from "./pages/student/Home";
import Profile from "./pages/student/Profile";
import Internships from "./pages/student/Internships";
import InternshipDetail from "./pages/student/InternshipDetail";
import Applications from "./pages/student/Applications";
import RecordPage from "./pages/Record";
import FacultyHome from "./pages/faculty/Home";
import Approvals from "./pages/faculty/Approvals";
import Students from "./pages/faculty/Students";
import StudentDetail from "./pages/faculty/StudentDetail";
import Opportunities from "./pages/faculty/Opportunities";
import Rules from "./pages/faculty/Rules";
import MentorHome from "./pages/mentor/Home";
import AdminHome from "./pages/admin/Home";
import Agents from "./pages/admin/Agents";
import Health from "./pages/admin/Health";
import Safety from "./pages/admin/Safety";

const NAV = {
  student: [["", "Home", "⌂"], ["internships", "Internships", "◎"], ["applications", "My applications", "▤"], ["profile", "Profile & resume", "☺"], ["activity", "Agent activity", "⚡"]],
  faculty: [["", "Dashboard", "⌂"], ["approvals", "Approvals", "✓"], ["students", "Students", "☺"], ["opportunities", "Internships", "◎"], ["rules", "Eligibility rules", "⚖"], ["activity", "Agent activity", "⚡"]],
  mentor: [["", "My interns", "☺"], ["activity", "Agent activity", "⚡"]],
  admin: [["", "Overview", "⌂"], ["activity", "Agent activity", "⚡"], ["agents", "Agents, MCP & runtime", "⚙"], ["health", "System health", "♥"], ["safety", "Audit & safety", "⛨"], ["students", "Students", "☺"], ["opportunities", "Internships", "◎"], ["rules", "Eligibility rules", "⚖"]],
};

function useHash() {
  const [hash, setHash] = useState(window.location.hash.slice(2));
  useEffect(() => {
    const f = () => { setHash(window.location.hash.slice(2)); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return hash.split("/").filter(Boolean);
}

export const go = (path) => { window.location.hash = `#/${path}`; };

function Bell({ unread, onOpen }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const toggle = async () => {
    if (!open) {
      setItems(await api.get("/notifications"));
      api.post("/notifications/read").then(onOpen);
    }
    setOpen(!open);
  };
  return (
    <>
      <button className="bell" onClick={toggle} title="Notifications">🔔{unread > 0 && <span className="dot">{unread}</span>}</button>
      {open && (
        <div className="notif-panel" onMouseLeave={() => setOpen(false)}>
          {items.length === 0 && <div className="item muted">No notifications yet.</div>}
          {items.map((n) => (
            <div key={n.id} className={`item ${n.read ? "" : "unread"}`}>
              {n.link ? <a href={n.link} onClick={() => setOpen(false)}>{n.text}</a> : n.text}
              <div className="small muted">{fmtTime(n.ts)}</div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default function App() {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(localStorage.getItem("portal_live") === "1");
  const route = useHash();

  const refresh = useCallback(() => api.get("/me").then(setMe).catch(() => setMe(null)), []);
  useEffect(() => {
    if (getToken()) refresh().finally(() => setLoading(false));
    else setLoading(false);
    const out = () => setMe(null);
    window.addEventListener("portal:logout", out);
    const t = setInterval(() => getToken() && refresh(), 15000);
    return () => { window.removeEventListener("portal:logout", out); clearInterval(t); };
  }, [refresh]);

  if (loading) return <div className="main">Loading…</div>;
  if (!me) return <Login onLogin={() => refresh().then(() => go(""))} />;

  const role = me.user.role;
  const [p0, p1] = route;
  const props = { me, refresh };
  let page;
  if (p0 === "records" && p1) page = <RecordPage id={p1} {...props} />;
  else if (p0 === "activity") page = <ActivityPage {...props} />;
  else if (role === "student") {
    page = p0 === "internships" && p1 ? <InternshipDetail id={p1} {...props} />
      : p0 === "internships" ? <Internships {...props} />
      : p0 === "applications" ? <Applications {...props} />
      : p0 === "profile" ? <Profile {...props} />
      : <StudentHome {...props} />;
  } else if (role === "faculty" || role === "admin") {
    page = p0 === "approvals" ? <Approvals {...props} />
      : p0 === "students" && p1 ? <StudentDetail id={p1} {...props} />
      : p0 === "students" ? <Students {...props} />
      : p0 === "opportunities" ? <Opportunities {...props} />
      : p0 === "rules" ? <Rules {...props} />
      : p0 === "agents" ? <Agents {...props} />
      : p0 === "health" ? <Health {...props} />
      : p0 === "safety" ? <Safety {...props} />
      : role === "admin" ? <AdminHome {...props} /> : <FacultyHome {...props} />;
  } else page = <MentorHome {...props} />;

  const logout = async () => { await api.post("/auth/logout").catch(() => {}); setToken(""); setMe(null); };
  const initials = me.user.name.replace(/^(Prof|Dr)\.\s*/, "").split(" ").map((w) => w[0]).slice(0, 2).join("");

  return (
    <div className={`layout ${live ? "with-drawer" : ""}`}>
      <aside className="sidebar">
        <div className="brand"><div className="brand-logo">◆</div><div>InternTrack<small>College Internship Portal</small></div></div>
        <nav className="nav">
          {NAV[role].map(([path, label, ico]) => (
            <a key={path} href={`#/${path}`} className={(p0 || "") === path ? "active" : ""}><span className="ico">{ico}</span>{label}</a>
          ))}
        </nav>
        <div className="side-foot">
          AI agents: {me.llm.provider === "groq" ? `on (${me.llm.model})` : "offline mode"}
          {me.llm.error && <div className="warn">Last AI call failed; using offline mode.</div>}
        </div>
      </aside>
      <main className="main">
        <div className="topbar">
          <button className="live-btn" onClick={() => { localStorage.setItem("portal_live", live ? "0" : "1"); setLive(!live); }}
            title="Show every agent, tool and AI call as it happens"><span className="pulse" />{live ? "Hide agent log" : "Show agent log"}</button>
          <Bell unread={me.unread} onOpen={refresh} />
          <div className="who">
            <div className="avatar">{initials}</div>
            <div><b>{me.user.name}</b><div className="small muted">{me.user.title}</div></div>
          </div>
          <button className="btn ghost" onClick={logout}>Log out</button>
        </div>
        {page}
      </main>
      {role === "student" && <Assistant />}
      {live && <ActivityDrawer onClose={() => { localStorage.setItem("portal_live", "0"); setLive(false); }} />}
    </div>
  );
}
