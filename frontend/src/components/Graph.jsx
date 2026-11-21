// Draws the workflow graph defined in portal/graph.py.
const R1 = 70, R2 = 220;
const POS = {
  resume: [75, R1], discovery: [240, R1], eligibility: [405, R1], application: [570, R1], apply: [735, R1], offer: [900, R1],
  approval: [900, R2], noc: [735, R2], progress: [570, R2], evaluation: [405, R2], grade: [240, R2], done: [75, R2],
  stop: [1050, 145],
};
const CURVE = { "noc>stop": 70, "grade>evaluation": 55 };
const W = 136, H = 40;
const FILL = { agent: "#edf2ff", human: "#fdf2dd", end: "#eef0f4" };
const STROKE = { agent: "#2f5bea", human: "#c27c0e", end: "#9aa3b5" };

function path(a, b) {
  const [x1, y1] = POS[a], [x2, y2] = POS[b];
  const bend = CURVE[`${a}>${b}`];
  if (bend) return `M${x1},${y1 + H / 2} C${x1},${y1 + bend} ${x2},${y2 + bend + 60} ${x2},${y2 + H / 2}`;
  if (x1 === x2) { const d = y2 > y1 ? 1 : -1; return `M${x1},${y1 + d * H / 2} L${x2},${y2 - d * H / 2}`; }
  if (y1 === y2) { const d = x2 > x1 ? 1 : -1; return `M${x1 + d * W / 2},${y1} L${x2 - d * W / 2},${y2}`; }
  return `M${x1 + (x2 > x1 ? W / 2 : -W / 2)},${y1} L${x2 + (x2 > x1 ? -W / 2 : W / 2)},${y2}`;
}

export default function Graph({ g, active }) {
  if (!g) return null;
  return (
    <div className="graph">
      <svg viewBox="0 0 1130 320">
        <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#9aa3b5" /></marker></defs>
        {g.edges.map((e, i) => (
          <path key={i} d={path(e.from, e.to)} fill="none" stroke="#c3c9d6" strokeWidth="1.5" markerEnd="url(#arr)"
            strokeDasharray={["noc>offer", "noc>stop", "grade>evaluation", "offer>stop"].includes(`${e.from}>${e.to}`) ? "4 3" : ""}>
            <title>{`${e.from} → ${e.to}: ${e.label}`}</title>
          </path>
        ))}
        {g.nodes.map((n) => {
          const [x, y] = POS[n.id];
          const on = active === n.id;
          return (
            <g key={n.id}>
              <title>{n.label}</title>
              <rect x={x - W / 2} y={y - H / 2} width={W} height={H} rx={n.type === "human" ? 20 : 9}
                fill={on ? STROKE[n.type] : FILL[n.type]} stroke={STROKE[n.type]} strokeWidth={on ? 2.5 : 1.2} />
              <text x={x} y={y + 4} textAnchor="middle" fill={on ? "#fff" : "#1b2234"}>{n.label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
