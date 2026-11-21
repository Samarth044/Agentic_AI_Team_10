import { useState } from "react";
import { api, setToken } from "../api";
import { Alert, Button, Field } from "../ui";

const DEMO = [
  ["Student", "ananya@college.edu", "student123"],
  ["Coordinator", "coordinator@college.edu", "faculty123"], ["Industry mentor", "arjun.mehta@industry.com", "mentor123"],
  ["Admin", "admin@college.edu", "admin123"],
];

export default function Login({ onLogin }) {
  const [mode, setMode] = useState("login");
  const [f, setF] = useState({ email: "", password: "", name: "", usn: "", department: "CSE", semester: 6 });
  const [err, setErr] = useState("");
  const bind = (k) => ({ value: f[k], onChange: (e) => setF({ ...f, [k]: e.target.value }) });

  const submit = async () => {
    setErr("");
    try {
      const r = mode === "login"
        ? await api.post("/auth/login", { email: f.email, password: f.password })
        : await api.post("/auth/register", f);
      setToken(r.token);
      onLogin();
    } catch (e) { setErr(e.message); }
  };

  return (
    <div className="auth">
      <div className="auth-hero">
        <div className="brand" style={{ padding: 0, marginBottom: 28 }}><div className="brand-logo">◆</div><div>InternTrack<small>College Internship Portal</small></div></div>
        <h1>From your resume to a graded internship, in one place.</h1>
        <ul>
          <li>Upload your resume. AI agents read it and match you to internships with a relevance score.</li>
          <li>See what you have, what you lack and whether you are eligible, before you apply.</li>
          <li>Get a tailored cover letter, apply on the company site, and track every step.</li>
          <li>NOC approval, weekly logs, mentor feedback and your final grade, all in one record.</li>
        </ul>
      </div>
      <div className="auth-form">
        <form className="box" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <h2>{mode === "login" ? "Log in" : "Create your student account"}</h2>
          <p className="muted">{mode === "login" ? "Welcome back." : "It takes a minute. You can add your resume next."}</p>
          <div className="form mt">
            <Alert>{err}</Alert>
            {mode === "register" && <Field label="Full name"><input {...bind("name")} required /></Field>}
            <Field label="Email"><input type="email" {...bind("email")} required /></Field>
            <Field label="Password"><input type="password" {...bind("password")} required /></Field>
            {mode === "register" && (
              <div className="form-row">
                <Field label="USN"><input {...bind("usn")} /></Field>
                <Field label="Branch"><select {...bind("department")}>{["CSE", "AI", "ECE", "ME", "CE"].map((b) => <option key={b}>{b}</option>)}</select></Field>
                <Field label="Semester"><input type="number" min="1" max="8" {...bind("semester")} /></Field>
              </div>
            )}
            <Button kind="primary lg" type="submit">{mode === "login" ? "Log in" : "Create account"}</Button>
            <div className="small">
              {mode === "login"
                ? <>New student? <a onClick={() => setMode("register")}>Create an account</a></>
                : <>Already registered? <a onClick={() => setMode("login")}>Log in</a></>}
            </div>
          </div>
          {mode === "login" && (
            <div className="demo">
              <b>Demo accounts</b> (click to fill)
              {DEMO.map(([role, email, pw]) => (
                <div key={email} className="spread"><span className="muted">{role}</span>
                  <button type="button" onClick={() => setF({ ...f, email, password: pw })}>{email}</button></div>
              ))}
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
