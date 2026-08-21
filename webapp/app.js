
async function readZip(buffer) {
  const u8 = new Uint8Array(buffer);
  const dv = new DataView(buffer);
  let eocd = -1;
  const floor = Math.max(0, u8.length - 66000);
  for (let i = u8.length - 22; i >= floor; i--) {
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error("That file is not a valid .xlsx (no zip found).");
  const count = dv.getUint16(eocd + 10, true);
  let p = dv.getUint32(eocd + 16, true);
  const entries = new Map();
  const dec = new TextDecoder();
  for (let n = 0; n < count; n++) {
    if (dv.getUint32(p, true) !== 0x02014b50) break;
    const method = dv.getUint16(p + 10, true);
    const csize = dv.getUint32(p + 20, true);
    const fnLen = dv.getUint16(p + 28, true);
    const exLen = dv.getUint16(p + 30, true);
    const cmLen = dv.getUint16(p + 32, true);
    const lho = dv.getUint32(p + 42, true);
    const name = dec.decode(u8.subarray(p + 46, p + 46 + fnLen));
    entries.set(name, { method, csize, lho });
    p += 46 + fnLen + exLen + cmLen;
  }
  return { u8, dv, entries };
}

async function readEntry(zip, name) {
  const e = zip.entries.get(name);
  if (!e) return null;
  const fnLen = zip.dv.getUint16(e.lho + 26, true);
  const exLen = zip.dv.getUint16(e.lho + 28, true);
  const start = e.lho + 30 + fnLen + exLen;
  const data = zip.u8.subarray(start, start + e.csize);
  if (e.method === 0) return new TextDecoder().decode(data);
  if (e.method !== 8) throw new Error("Unsupported compression in the .xlsx file.");
  const stream = new Blob([data]).stream()
    .pipeThrough(new DecompressionStream("deflate-raw"));
  return await new Response(stream).text();
}

const xml = s => new DOMParser().parseFromString(s, "application/xml");

function colIndex(ref) {
  let n = 0;
  for (let i = 0; i < ref.length; i++) {
    const c = ref.charCodeAt(i);
    if (c < 65 || c > 90) break;
    n = n * 26 + (c - 64);
  }
  return n - 1;
}

function serialToDate(n) {
  return new Date(Math.round((n - 25569) * 86400000));
}

async function parseWorkbook(buffer) {
  const zip = await readZip(buffer);
  const wbXml = await readEntry(zip, "xl/workbook.xml");
  if (!wbXml) throw new Error("That .xlsx has no workbook inside it.");
  const relsXml = await readEntry(zip, "xl/_rels/workbook.xml.rels");

  const rels = new Map();
  if (relsXml) {
    for (const r of xml(relsXml).getElementsByTagName("Relationship")) {
      rels.set(r.getAttribute("Id"), r.getAttribute("Target").replace(/^\/?xl\//, ""));
    }
  }

  const shared = [];
  const ssXml = await readEntry(zip, "xl/sharedStrings.xml");
  if (ssXml) {
    for (const si of xml(ssXml).getElementsByTagName("si")) {
      let text = "";
      for (const t of si.getElementsByTagName("t")) text += t.textContent;
      shared.push(text);
    }
  }

  const sheets = [];
  const wb = xml(wbXml);
  let auto = 0;
  for (const sh of wb.getElementsByTagName("sheet")) {
    auto++;
    const rid = sh.getAttribute("r:id") ||
      sh.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id");
    const target = (rels.get(rid) || `worksheets/sheet${auto}.xml`).replace(/^\//, "");
    const sheetXml = await readEntry(zip, "xl/" + target) ||
                     await readEntry(zip, target);
    if (!sheetXml) continue;
    sheets.push({ name: sh.getAttribute("name"), rows: sheetRows(sheetXml, shared) });
  }
  return sheets;
}

function sheetRows(sheetXml, shared) {
  const doc = xml(sheetXml);
  const out = [];
  for (const row of doc.getElementsByTagName("row")) {
    const cells = [];
    let max = -1;
    for (const c of row.getElementsByTagName("c")) {
      const ref = c.getAttribute("r") || "";
      const idx = ref ? colIndex(ref) : max + 1;
      const type = c.getAttribute("t");
      let value = null;
      if (type === "inlineStr") {
        let t = "";
        for (const n of c.getElementsByTagName("t")) t += n.textContent;
        value = t;
      } else {
        const v = c.getElementsByTagName("v")[0];
        if (v) {
          if (type === "s") value = shared[parseInt(v.textContent, 10)] ?? "";
          else if (type === "str" || type === "e") value = v.textContent;
          else if (type === "b") value = v.textContent === "1";
          else value = parseFloat(v.textContent);
        }
      }
      cells[idx] = value;
      if (idx > max) max = idx;
    }
    for (let i = 0; i <= max; i++) if (cells[i] === undefined) cells[i] = null;
    out.push(cells);
  }
  return out;
}

const HEADER_ALIASES = {
  governor_id: ["governor id", "governorid", "id", "player id", "lord id"],
  name: ["name", "governor name", "nickname", "player"],
  rank: ["rank", "alliance rank"],
  title: ["title"],
  home_kingdom: ["home kingdom", "kingdom", "home"],
  city_hall: ["city hall", "ch", "city hall level"],
  power: ["power"],
  kill_score: ["kill score", "killscore", "kp", "kill points"],
  kills: ["kills", "total kills"],
  tech_donations: ["tech donations", "technology donations", "tech donation"],
  building_time_s: ["building time (s)", "building time", "build time (s)"],
  times_helped: ["times helped", "helps", "helps given"],
  resources_donated: ["resources donated", "resource donated", "resources"],
  forts_destroyed: ["forts destroyed", "forts", "flags destroyed"],
  armory_points: ["armory points", "armory", "armoury points"],
  last_login: ["last login (utc)", "last login"],
  days_inactive: ["days inactive", "inactive days"],
  days_in_alliance: ["days in alliance", "days in ally"],
};
const LOOKUP = {};
for (const [field, aliases] of Object.entries(HEADER_ALIASES))
  for (const a of aliases) LOOKUP[a] = field;

const SUMMARY_ALIASES = {
  alliance_name: ["alliance", "alliance name"], tag: ["tag", "alliance tag"],
  kingdom: ["kingdom"], leader: ["leader"], member_count: ["members", "member count"],
};
const SUMMARY_LOOKUP = {};
for (const [f, aliases] of Object.entries(SUMMARY_ALIASES))
  for (const a of aliases) SUMMARY_LOOKUP[a] = f;

const ACTIVITY_FIELDS = ["kill_score", "kills", "tech_donations", "building_time_s",
  "times_helped", "resources_donated", "forts_destroyed", "armory_points"];
const NUMERIC = new Set([...ACTIVITY_FIELDS, "power", "city_hall",
  "days_inactive", "days_in_alliance", "governor_id"]);

const norm = v => v == null ? "" : String(v).normalize("NFKC").trim().toLowerCase().replace(/\s+/g, " ");

function num(v) {
  if (v == null || v === "") return 0;
  if (typeof v === "number") return v;
  if (typeof v === "boolean") return v ? 1 : 0;
  let s = String(v).trim().replace(/,/g, "").replace(/\s/g, "");
  let mult = 1;
  const last = s.slice(-1).toLowerCase();
  if ("kmb".includes(last) && s.length > 1) {
    mult = { k: 1e3, m: 1e6, b: 1e9 }[last];
    s = s.slice(0, -1);
  }
  const f = parseFloat(s);
  return isNaN(f) ? 0 : f * mult;
}

function findHeader(rows, required, lookup) {
  for (let r = 0; r < Math.min(10, rows.length); r++) {
    const map = {};
    const seen = new Set();
    rows[r].forEach((cell, i) => {
      const field = lookup[norm(cell)];
      if (field && !seen.has(field)) { map[i] = field; seen.add(field); }
    });
    if (required.every(f => seen.has(f))) return { row: r, map };
  }
  return null;
}

export async function parseMembers(buffer) {
  const sheets = await parseWorkbook(buffer);
  const members = [];
  const summaries = [];

  for (const sheet of sheets) {
    if (!sheet.rows.length) continue;

    let hit = findHeader(sheet.rows, ["governor_id", "power"], LOOKUP);
    if (!hit) {
      const s = findHeader(sheet.rows, ["alliance_name", "tag"], SUMMARY_LOOKUP);
      if (s) {
        for (const row of sheet.rows.slice(s.row + 1)) {
          const rec = {};
          for (const [i, f] of Object.entries(s.map)) rec[f] = row[i];
          if (!rec.tag) continue;
          summaries.push({
            tag: String(rec.tag).trim(),
            alliance_name: String(rec.alliance_name ?? "").trim(),
            kingdom: String(rec.kingdom ?? "").trim(),
            leader: String(rec.leader ?? "").trim(),
          });
        }
      }
      continue;
    }
    for (const row of sheet.rows.slice(hit.row + 1)) {
      const rec = {};
      for (const [i, f] of Object.entries(hit.map)) rec[f] = row[i];
      if (rec.governor_id == null || rec.governor_id === "") continue;
      const m = { alliance_tag: String(sheet.name).trim() };
      for (const field of Object.keys(HEADER_ALIASES)) {
        const v = rec[field];
        if (NUMERIC.has(field)) m[field] = num(v);
        else if (field === "last_login") m[field] = typeof v === "number" ? v : null;
        else m[field] = v == null ? null : String(v).trim();
      }
      m.governor_id = Math.round(m.governor_id);
      m.name = m.name || ("Governor " + m.governor_id);
      members.push(m);
    }
  }

  if (!members.length)
    throw new Error("No member rows found - is this the alliance export?");

  const best = new Map();
  for (const m of members) {
    const prior = best.get(m.governor_id);
    if (!prior || (m.last_login || 0) > (prior.last_login || 0)) best.set(m.governor_id, m);
  }
  const list = [...best.values()];
  const logins = list.map(m => m.last_login).filter(Boolean);
  const scanSerial = logins.length ? Math.max(...logins) : null;

  return {
    members: list,
    summaries,
    scanDate: scanSerial ? serialToDate(scanSerial).toISOString() : null,
  };
}

export const METRIC_LABELS = {
  kill_score: "Kills +", kills: "Kills", tech_donations: "Tech Donations",
  building_time_s: "Building Time", times_helped: "Helps",
  resources_donated: "Resources Donated", forts_destroyed: "Forts Destroyed",
  armory_points: "Armory Points", power_growth: "Power Growth",
};
export const TIER_ORDER = ["S", "A", "B", "C", "D", "F"];

export function detectModes(weeks, cfg) {
  const modes = {}, why = {};
  const limit = cfg.scoring.cumulative_max_decrease ?? 0.15;
  for (const name of ACTIVITY_FIELDS) {
    const want = String(cfg.metric_mode?.[name] ?? "auto").toLowerCase();
    if (want === "delta" || want === "raw") { modes[name] = want; why[name] = "set manually"; continue; }
    let up = 0, down = 0;
    for (let i = 1; i < weeks.length; i++) {
      const prior = new Map(weeks[i - 1].members.map(m => [m.governor_id, m]));
      for (const m of weeks[i].members) {
        const p = prior.get(m.governor_id);
        if (!p) continue;
        const a = +p[name] || 0, b = +m[name] || 0;
        if (b > a) up++; else if (b < a) down++;
      }
    }
    const total = up + down;
    if (total < 20) { modes[name] = "raw"; why[name] = "only one week of data so far"; }
    else if (down / total <= limit) {
      modes[name] = "delta"; why[name] = `accumulates (${Math.round(down / total * 100)}% fell)`;
    } else {
      modes[name] = "raw"; why[name] = `resets each week (${Math.round(down / total * 100)}% fell)`;
    }
  }
  return { modes, why };
}

function percentileOf(sorted, q) {
  if (!sorted.length) return 0;
  if (sorted.length === 1) return sorted[0];
  const pos = (sorted.length - 1) * (q / 100);
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  if (lo === hi) return sorted[pos];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

function rankScores(values, curve, capPct) {
  const n = values.length;
  if (!n) return [];
  if (n === 1) return [values[0] > 0 ? 100 : 0];
  const order = values.map((_, i) => i).sort((a, b) => values[a] - values[b]);
  const lowest = new Map();
  order.forEach((idx, pos) => { if (!lowest.has(values[idx])) lowest.set(values[idx], pos); });
  const pct = values.map(v => lowest.get(v) / (n - 1) * 100);
  const ordered = order.map(i => values[i]);
  let cap = percentileOf(ordered, capPct);
  if (cap <= 0) cap = ordered[ordered.length - 1] || 1;
  const normed = values.map(v => Math.min(v / cap, 1) * 100);
  if (curve === "percentile") return pct;
  if (curve === "normalized") return normed;
  return pct.map((p, i) => (p + normed[i]) / 2);
}

function inactivityFactor(days, penalties) {
  let factor = 1;
  for (const [threshold, mult] of [...penalties].sort((a, b) => a[0] - b[0]))
    if (days >= threshold) factor = mult;
  return factor;
}

function tierFor(pct, cuts) {
  for (const t of TIER_ORDER.slice(0, -1)) if (pct >= (cuts[t] ?? 0)) return t;
  return "F";
}

export function scoreWeek(week, previous, cfg, modes) {
  const s = cfg.scoring;
  const curve = s.curve ?? "hybrid";
  const capPct = s.cap_percentile ?? 95;
  const poolMode = s.pool ?? "global";
  const newDelta = String(s.new_member_delta ?? "median").toLowerCase();
  const penalties = cfg.inactivity.penalties;
  const flagsCfg = cfg.flags;

  const members = week.members.map(m => ({ ...m }));
  const prevById = new Map((previous?.members ?? []).map(m => [m.governor_id, m]));
  const hasPrevious = !!previous;

  for (const m of members) {
    const prior = prevById.get(m.governor_id);
    m.has_baseline = !!prior;
    m.power_growth = prior ? Math.max(0, m.power - prior.power) : 0;
  }

  const effModes = {};
  for (const name of ACTIVITY_FIELDS)
    effModes[name] = modes[name] === "delta" ? "delta" : "raw";

  for (const m of members) {
    const prior = prevById.get(m.governor_id);
    for (const name of ACTIVITY_FIELDS) {
      const raw = +m[name] || 0;
      m["total_" + name] = raw;
      if (effModes[name] !== "delta") m["eff_" + name] = raw;

      else if (!hasPrevious) m["eff_" + name] = 0;
      else if (prior) m["eff_" + name] = Math.max(0, raw - (+prior[name] || 0));
      else m["eff_" + name] = null;
    }
    m.eff_power_growth = m.power_growth;
  }
  const usesDelta = Object.values(effModes).includes("delta");

  for (const name of ACTIVITY_FIELDS) {
    if (effModes[name] !== "delta") continue;
    const known = members.map(m => m["eff_" + name]).filter(v => v !== null).sort((a, b) => a - b);
    let fill = known.length ? known[Math.floor(known.length / 2)] : 0;
    if (newDelta === "zero") fill = 0;
    for (const m of members)
      if (m["eff_" + name] === null)
        m["eff_" + name] = newDelta === "raw" ? m["total_" + name] : fill;
  }

  const metrics = [];
  for (const [name, w] of Object.entries(cfg.weights)) {
    const weight = +w || 0;
    if (weight <= 0) continue;
    if (!ACTIVITY_FIELDS.includes(name) && name !== "power_growth") continue;
    if (name === "power_growth" && !hasPrevious) continue;
    if (members.every(m => (+m["eff_" + name] || 0) === 0)) continue;
    metrics.push([name, weight]);
  }
  metrics.sort((a, b) => b[1] - a[1]);
  const totalWeight = metrics.reduce((a, [, w]) => a + w, 0) || 1;

  for (const m of members)
    for (const [name] of metrics) m["adj_" + name] = +m["eff_" + name] || 0;

  const pools = new Map();
  if (poolMode === "alliance") {
    for (const m of members) {
      if (!pools.has(m.alliance_tag)) pools.set(m.alliance_tag, []);
      pools.get(m.alliance_tag).push(m);
    }
  } else pools.set("__global__", members);

  for (const pool of pools.values()) {
    for (const [name] of metrics) {
      const vals = pool.map(m => +m["adj_" + name] || 0);
      const scores = rankScores(vals, curve, capPct);
      pool.forEach((m, i) => { m["score_" + name] = scores[i]; });
    }
    for (const m of pool) {
      const base = metrics.reduce((a, [n, w]) => a + m["score_" + n] * w, 0) / totalWeight;
      m.base_score = base;
      m.inactivity_factor = inactivityFactor(+m.days_inactive || 0, penalties);
      m.score = Math.round(base * m.inactivity_factor * 100) / 100;
    }
    const sorted = pool.map(m => m.score).sort((a, b) => a - b);
    for (const m of pool) {
      const below = sorted.filter(v => v < m.score).length;
      m.score_percentile = sorted.length > 1 ? below / (sorted.length - 1) * 100 : 100;
      m.tier = tierFor(m.score_percentile, cfg.tiers);
    }
  }

  const catMap = cfg.categories ?? {};
  const catWeights = {};
  for (const [name, w] of metrics) {
    const c = catMap[name] ?? "Other";
    catWeights[c] = (catWeights[c] ?? 0) + w;
  }
  for (const m of members) {
    const totals = {};
    for (const [name, w] of metrics) {
      const c = catMap[name] ?? "Other";
      totals[c] = (totals[c] ?? 0) + m["score_" + name] * w;
    }
    m.categories = {};
    for (const [c, t] of Object.entries(totals))
      m.categories[c] = Math.round(t / catWeights[c] * 10) / 10;
  }

  members.sort((a, b) => b.score - a.score);
  members.forEach((m, i) => { m.rank_overall = i + 1; });
  const byAlliance = new Map();
  for (const m of members) {
    if (!byAlliance.has(m.alliance_tag)) byAlliance.set(m.alliance_tag, []);
    byAlliance.get(m.alliance_tag).push(m);
  }
  for (const g of byAlliance.values())
    [...g].sort((a, b) => b.score - a.score).forEach((m, i) => { m.rank_in_alliance = i + 1; });

  for (const m of members) {
    const p = prevById.get(m.governor_id);
    m.prev_rank = p?.rank_overall ?? null;
    m.rank_change = p?.rank_overall ? p.rank_overall - m.rank_overall : null;
    m.prev_score = p?.score ?? null;
    m.score_change = p?.score != null ? Math.round((m.score - p.score) * 100) / 100 : null;
  }

  const inactiveDays = flagsCfg.inactive_days ?? 7;
  const deadDays = flagsCfg.dead_days ?? 14;
  const lowScore = flagsCfg.low_score ?? 25;
  for (const m of members) {
    const tags = [];
    const d = +m.days_inactive || 0;
    if (d >= deadDays) tags.push("DEAD");
    else if (d >= inactiveDays) tags.push("INACTIVE");
    if (m.score < lowScore && !tags.includes("DEAD")) tags.push("LOW");
    if (["tech_donations", "times_helped", "building_time_s"]
        .every(f => (+m["eff_" + f] || 0) === 0)) tags.push("NO SUPPORT");
    if (usesDelta && hasPrevious && !m.has_baseline) tags.push("NO BASELINE");
    m.flags = tags;
  }

  const meta = new Map((week.summaries ?? []).map(s => [s.tag, s]));
  const prevAvg = new Map();
  if (previous) {
    const tmp = new Map();
    for (const m of previous.members) {
      if (!tmp.has(m.alliance_tag)) tmp.set(m.alliance_tag, []);
      tmp.get(m.alliance_tag).push(m.score ?? 0);
    }
    for (const [t, v] of tmp) prevAvg.set(t, v.reduce((a, b) => a + b, 0) / v.length);
  }

  const alliances = [];
  for (const [tag, g] of byAlliance) {
    const avg = g.reduce((a, m) => a + m.score, 0) / g.length;
    const prior = prevAvg.get(tag);
    const totals = {};
    for (const [name] of metrics)
      totals[name] = g.reduce((a, m) => a + (+m["eff_" + name] || 0), 0);
    alliances.push({
      tag, name: meta.get(tag)?.alliance_name || tag,
      members: g.length,
      avg_score: Math.round(avg * 100) / 100,
      median_score: Math.round([...g].sort((a, b) => a.score - b.score)[Math.floor(g.length / 2)].score * 100) / 100,
      avg_change: prior != null ? Math.round((avg - prior) * 100) / 100 : null,
      total_power: g.reduce((a, m) => a + (+m.power || 0), 0),
      inactive: g.filter(m => m.flags.includes("INACTIVE") || m.flags.includes("DEAD")).length,
      top_tier: g.filter(m => m.tier === "S" || m.tier === "A").length,
      totals,
    });
  }
  alliances.sort((a, b) => b.avg_score - a.avg_score);
  alliances.forEach((a, i) => { a.rank = i + 1; });

  return {
    label: week.label, scanDate: week.scanDate, members, alliances,
    metrics: metrics.map(([n]) => n), metricModes: effModes, usesDelta,
    hasPrevious, previousLabel: previous?.label ?? null,
    tierCounts: Object.fromEntries(TIER_ORDER.map(t =>
      [t, members.filter(m => m.tier === t).length])),
  };
}

export function scoreAll(weeks, cfg) {
  const { modes, why } = detectModes(weeks, cfg);
  const results = [];
  let prev = null;
  for (const w of weeks) {
    const r = scoreWeek(w, prev, cfg, modes);
    results.push(r);
    prev = { label: w.label, members: r.members };
  }
  return { results, modes, why };
}

export function departures(current, previous) {
  if (!previous) return [];
  const now = new Set(current.members.map(m => m.governor_id));
  return previous.members.filter(m => !now.has(m.governor_id))
    .map(m => ({
      governor_id: m.governor_id, name: m.name, alliance_tag: m.alliance_tag,
      power: m.power, last_score: m.score ?? null, last_tier: m.tier ?? null,
    }))
    .sort((a, b) => b.power - a.power);
}

