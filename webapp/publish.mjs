// Headless publisher — scores the saved state with the real engine (app.js)
// and sends a snapshot to myprojects-site, no browser needed. Good for a
// scheduled task or CI.
//
//   node webapp/publish.mjs path/to/state.json            # print the snapshot
//   MYPROJECTS_TOKEN=xxx node webapp/publish.mjs state.json --dispatch
//
// MYPROJECTS_REPO defaults to mtc53/myprojects-site.
import { readFileSync } from "node:fs";
import { scoreAll } from "./app.js";

const file = process.argv[2];
if (!file) { console.error("usage: node webapp/publish.mjs <state.json> [--dispatch]"); process.exit(2); }

const state = JSON.parse(readFileSync(file, "utf-8"));
const weeks = state.weeks || [];
if (!weeks.length) { console.error("no weeks in state"); process.exit(1); }

const { results } = scoreAll(weeks, state.config || {});
const week = results[results.length - 1];
const members = (week.members || []).slice()
  .sort((a, b) => (a.rank_overall || 1e9) - (b.rank_overall || 1e9));
const alliances = new Set(members.map(m => m.alliance_tag).filter(Boolean));
const top = members.slice(0, 10).map(m => [
  "#" + (m.rank_overall ?? "—"),
  m.name || ("Governor " + m.governor_id),
  m.alliance_tag || "",
  (m.score ?? 0).toLocaleString("en-US"),
]);

const data = {
  project: "warroom",
  title: "Kingdom War Room",
  updated: new Date().toISOString(),
  status: "ok",
  summary: `${week.label} scored — ${members.length} governors across ${alliances.size} alliance${alliances.size === 1 ? "" : "s"}.`,
  stats: [
    { label: "Governors", value: String(members.length) },
    { label: "Alliances", value: String(alliances.size) },
    { label: "Week", value: String(week.label) },
  ],
  sections: top.length ? [{ heading: "Top governors", columns: ["Rank", "Governor", "Alliance", "Score"], rows: top }] : [],
  source: "https://github.com/mtc53/rok-ranking-assistant",
};

if (!process.argv.includes("--dispatch")) {
  console.log(JSON.stringify(data, null, 2));
  process.exit(0);
}

const token = (process.env.MYPROJECTS_TOKEN || "").trim();
const repo = process.env.MYPROJECTS_REPO || "mtc53/myprojects-site";
if (!token) { console.error("--dispatch needs MYPROJECTS_TOKEN"); process.exit(1); }

const res = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
  method: "POST",
  headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json", "Content-Type": "application/json" },
  body: JSON.stringify({ event_type: "publish-data", client_payload: { project: "warroom", data } }),
});
if (res.ok) console.error(`dispatched to ${repo}`);
else { console.error(`${repo} returned ${res.status}`); process.exit(1); }
