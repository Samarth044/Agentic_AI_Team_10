import { useState } from "react";
import { api } from "../../api";
import { Card, Tabs, useLoad } from "../../ui";
import { QueueTable } from "./Home";

export default function Approvals() {
  const [rows] = useLoad(() => api.get("/records"));
  const [tab, setTab] = useState("pending");
  if (!rows) return <p>Loading…</p>;
  const pending = rows.filter((r) => ["NOC_PENDING", "GRADE_PENDING"].includes(r.stage));
  const lists = {
    pending, noc: rows.filter((r) => r.stage === "NOC_PENDING"), grade: rows.filter((r) => r.stage === "GRADE_PENDING"),
    all: rows,
  };
  return (
    <>
      <div className="page-head"><div><h1>Approvals</h1><div className="muted">The Approval Agent checks each case and recommends; only you can approve.</div></div></div>
      <Tabs tabs={[["pending", `Waiting (${pending.length})`], ["noc", "NOC requests"], ["grade", "Grade sign-offs"], ["all", "All records"]]} value={tab} onChange={setTab} />
      <Card><QueueTable rows={lists[tab]} /></Card>
    </>
  );
}
