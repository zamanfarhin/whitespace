"use client";

import { useEffect, useMemo, useState } from "react";
import {
  coverageOf, host, money, quadrantOf, scoreOf, tierOf,
} from "./lib";

const W = 640, H = 440;
const PAD = { l: 62, r: 26, t: 26, b: 54 };
const PLOT_W = W - PAD.l - PAD.r;
const PLOT_H = H - PAD.t - PAD.b;

const x = (fit) => PAD.l + (fit / 100) * PLOT_W;
const y = (lev) => PAD.t + PLOT_H - (lev / 100) * PLOT_H;

export default function Page() {
  const [leads, setLeads] = useState(null);
  const [error, setError] = useState(null);
  const [weights, setWeights] = useState(null);
  const [selected, setSelected] = useState(0);
  const [eventFilter, setEventFilter] = useState(null);

  useEffect(() => {
    fetch("leads.json")
      .then((r) => {
        if (!r.ok) throw new Error(`leads.json returned ${r.status}`);
        return r.json();
      })
      .then((rows) => {
        const live = rows.filter(
          (l) => !l.qualification?.unassessed
            && !l.qualification?.disqualified_reason
            && (l.qualification?.components || []).length > 0,
        );
        setLeads(live);
        const base = {};
        for (const c of live[0]?.qualification?.components || []) base[c.name] = c.weight;
        setWeights(base);
      })
      .catch((e) => setError(e.message));
  }, []);

  const defaults = useMemo(() => {
    const base = {};
    for (const c of leads?.[0]?.qualification?.components || []) base[c.name] = c.weight;
    return base;
  }, [leads]);

  const events = useMemo(() => {
    const seen = new Map();
    for (const l of leads || []) {
      for (const a of l.company.appearances || []) {
        seen.set(a.event_slug, (seen.get(a.event_slug) || 0) + 1);
      }
    }
    return [...seen.entries()].sort((a, b) => b[1] - a[1]);
  }, [leads]);

  const points = useMemo(() => {
    if (!leads) return [];
    return leads
      .filter((lead) => !eventFilter
        || (lead.company.appearances || []).some((a) => a.event_slug === eventFilter))
      .map((lead, i) => {
        const fit = scoreOf(lead.qualification.components, weights);
        const lev = scoreOf(lead.leverage?.components, null);
        return { i, lead, fit, lev, coverage: coverageOf(lead) };
      }).sort((a, b) => b.fit - a.fit);
  }, [leads, weights, eventFilter]);

  if (error) {
    return (
      <main style={{ padding: 40 }}>
        <h1 className="wordmark">white<span>space</span></h1>
        <p className="empty" style={{ marginTop: 20, maxWidth: 520 }}>
          Could not load leads.json. Copy the pipeline output into the dashboard
          with <code>cp ../out/leads.json public/</code>, then reload. ({error})
        </p>
      </main>
    );
  }

  if (!leads || !weights) {
    return <main style={{ padding: 40 }} className="eyebrow">Loading leads</main>;
  }

  const active = points[selected] || points[0];
  const withPerson = points.filter((p) => (p.lead.stakeholders || []).length).length;
  const drafted = points.filter((p) => p.lead.outreach).length;
  const verified = points.filter(
    (p) => p.lead.outreach && (p.lead.outreach.unverified_claims || []).length === 0,
  ).length;

  return (
    <>
      <header className="masthead">
        <div>
          <div className="wordmark">white<span>space</span></div>
          <div className="subtitle">
            DuPont Tedlar · Graphics &amp; Signage · qualified from public exhibitor data
          </div>
        </div>
        <div className="runstats">
          <Stat k="qualified" v={points.length} />
          <Stat k="named contact" v={`${withPerson}/${points.length}`} />
          <Stat k="drafted" v={drafted} />
          <Stat k="passed check" v={`${verified}/${drafted || 0}`} />
        </div>
      </header>

      <div className="shell">
        <section className="left">
          <p className="eyebrow">source event</p>
          <div className="chips" style={{ marginBottom: 16 }}>
            <button className={`chip filter${eventFilter === null ? " on" : ""}`}
                    onClick={() => { setEventFilter(null); setSelected(0); }}>
              all events · {leads.length}
            </button>
            {events.map(([slug, n]) => (
              <button key={slug}
                      className={`chip filter${eventFilter === slug ? " on" : ""}`}
                      onClick={() => { setEventFilter(slug); setSelected(0); }}>
                {slug} · {n}
              </button>
            ))}
          </div>

          <p className="eyebrow">fit against leverage</p>
          <h2 className="section">Who to call, and who you can actually win</h2>
          <p style={{ fontSize: 13.5, color: "var(--ink-2)", margin: "6px 0 14px", maxWidth: 520 }}>
            Horizontal is how well a company fits the ideal customer. Vertical is
            how open the account looks. A ring&apos;s fill shows how much sourced
            evidence sits behind it, so a hollow ring is a lead we know little
            about rather than a lead that scored badly.
          </p>

          <svg className="plot" viewBox={`0 0 ${W} ${H}`} role="img"
               aria-label="Scatter plot of leads by ICP fit and leverage">
            <rect x={PAD.l} y={PAD.t} width={PLOT_W} height={PLOT_H}
                  fill="#fff" stroke="var(--rule)" strokeWidth="1" />
            <line x1={x(60)} y1={PAD.t} x2={x(60)} y2={PAD.t + PLOT_H}
                  stroke="var(--rule)" strokeDasharray="3 4" />
            <line x1={PAD.l} y1={y(60)} x2={PAD.l + PLOT_W} y2={y(60)}
                  stroke="var(--rule)" strokeDasharray="3 4" />

            <text className="quad-label" x={PAD.l + PLOT_W - 8} y={PAD.t + 16}
                  textAnchor="end">call now</text>
            <text className="quad-label" x={PAD.l + PLOT_W - 8} y={PAD.t + PLOT_H - 8}
                  textAnchor="end">displacement play</text>
            <text className="quad-label" x={PAD.l + 8} y={PAD.t + 16}>low priority</text>
            <text className="quad-label" x={PAD.l + 8} y={PAD.t + PLOT_H - 8}>hold</text>

            {[0, 50, 100].map((t) => (
              <text key={`x${t}`} x={x(t)} y={PAD.t + PLOT_H + 18} textAnchor="middle"
                    fontSize="10" fill="var(--ink-3)">{t}</text>
            ))}
            {[0, 50, 100].map((t) => (
              <text key={`y${t}`} x={PAD.l - 10} y={y(t) + 3} textAnchor="end"
                    fontSize="10" fill="var(--ink-3)">{t}</text>
            ))}
            <text x={PAD.l + PLOT_W / 2} y={H - 14} textAnchor="middle"
                  fontSize="11" fill="var(--ink-2)" letterSpacing="0.08em">ICP FIT</text>
            <text x={16} y={PAD.t + PLOT_H / 2} textAnchor="middle" fontSize="11"
                  fill="var(--ink-2)" letterSpacing="0.08em"
                  transform={`rotate(-90 16 ${PAD.t + PLOT_H / 2})`}>LEVERAGE</text>

            {points.map((p, idx) => {
              const r = 7 + p.coverage * 7;
              const on = idx === selected;
              return (
                <g key={p.lead.company.name} className="ring"
                   style={{ transform: `translate(${x(p.fit)}px, ${y(p.lev)}px)` }}
                   onClick={() => setSelected(idx)} tabIndex={0}
                   onKeyDown={(e) => e.key === "Enter" && setSelected(idx)}>
                  <title>{`${p.lead.company.name} — fit ${p.fit.toFixed(0)}, leverage ${p.lev.toFixed(0)}`}</title>
                  <circle r={r} fill={on ? "var(--uv-soft)" : "#fff"}
                          stroke={on ? "var(--uv)" : "var(--ink-2)"}
                          strokeWidth={on ? 3 : 1.5} />
                  <circle r={r * p.coverage} fill={on ? "var(--uv)" : "var(--ink-2)"}
                          fillOpacity={on ? 0.9 : 0.35} />
                </g>
              );
            })}
          </svg>

          <div className="weights">
            <p className="eyebrow" style={{ marginBottom: 8 }}>
              rubric weights · drag to retune, ranking updates live
            </p>
            {Object.keys(weights).map((name) => (
              <div key={name}
                   className={`weight-row${name === "environmental_severity" ? " severity" : ""}`}>
                <label className="weight-name" htmlFor={`w-${name}`}>
                  {name.replace(/_/g, " ")}
                </label>
                <input id={`w-${name}`} type="range" min="0" max="50" step="1"
                       value={weights[name]}
                       onChange={(e) =>
                         setWeights({ ...weights, [name]: Number(e.target.value) })} />
                <span className="weight-val">{weights[name]}</span>
              </div>
            ))}
            <button className="reset" onClick={() => setWeights(defaults)}>
              reset to config/icp.yaml
            </button>
          </div>
        </section>

        <section className="right">
          {active ? <Detail p={active} /> : <p className="empty">No qualified leads.</p>}
        </section>
      </div>
    </>
  );
}

function Stat({ k, v }) {
  return (
    <div>
      <div className="stat-k">{k}</div>
      <div className="stat-v">{v}</div>
    </div>
  );
}

function Detail({ p }) {
  const { lead, fit, lev } = p;
  const c = lead.company;
  const person = (lead.stakeholders || [])[0];
  const mail = lead.outreach;
  const flags = mail?.unverified_claims || [];

  const shows = [...new Set((c.appearances || []).map((a) => a.event_slug))];
  const booth = (c.appearances || []).find((a) => a.booth)?.booth;

  return (
    <>
      <p className="eyebrow">lead detail</p>
      <h1 className="lead-name">{c.name}</h1>

      <div className="chips">
        {shows.map((slug) => (
          <span key={slug} className="chip event">{slug}</span>
        ))}
        <span className="chip tier">tier {tierOf(fit)}</span>
        <span className="chip motion">{quadrantOf(fit, lev)}</span>
        <span className="chip">fit {fit.toFixed(0)}</span>
        <span className="chip">leverage {lev.toFixed(0)}</span>
        <span className="chip">{money(c)}</span>
        {booth && <span className="chip">booth {booth}</span>}
      </div>

      <p className="eyebrow">why it scored what it did</p>
      <div className="bars">
        {[...lead.qualification.components]
          .sort((a, b) => b.raw * b.weight - a.raw * a.weight)
          .map((comp) => (
            <div key={comp.name}>
              <div className="bar-row">
                <span className="bar-name">{comp.name.replace(/_/g, " ")}</span>
                <span className="bar-track">
                  <span className={`bar-fill${comp.name === "environmental_severity" ? " heat" : ""}`}
                        style={{ width: `${comp.raw * 100}%` }} />
                </span>
                <span className="bar-pts">{(comp.raw * comp.weight).toFixed(0)}</span>
                <span className="bar-why">{comp.rationale}</span>
              </div>
            </div>
          ))}
      </div>

      <p className="eyebrow">evidence, with sources</p>
      <div className="evidence">
        <Ev label="website" s={c.website} />
        <Ev label="revenue" s={c.revenue_usd || c.revenue_band} />
        <Ev label="headcount" s={c.employees_band || c.employees} />
        <Ev label="hq" s={c.hq_city} />
        {(c.product_lines || []).slice(0, 3).map((s, i) => (
          <Ev key={`p${i}`} label={i === 0 ? "products" : ""} s={s} />
        ))}
        {(c.recent_signals || []).slice(0, 2).map((s, i) => (
          <Ev key={`s${i}`} label={i === 0 ? "activity" : ""} s={s} />
        ))}
        {shows.length > 0 && (
          <div className="ev-row">
            <span className="ev-label">exhibits at</span>
            <span className="ev-val">{shows.join(", ")}</span>
          </div>
        )}
      </div>

      <p className="eyebrow">decision maker</p>
      {person ? (
        <div className="person">
          <div className="person-name">{person.full_name}</div>
          <div className="person-title">{person.title}</div>
          <div className="person-links">
            {person.linkedin_url && (
              <a href={person.linkedin_url.value} target="_blank" rel="noreferrer">linkedin</a>
            )}
            {person.sales_nav_url && (
              <a href={person.sales_nav_url} target="_blank" rel="noreferrer">
                sales navigator search
              </a>
            )}
            {person.source?.url && (
              <a href={person.source.url} target="_blank" rel="noreferrer">
                found at {host(person.source.url)}
              </a>
            )}
          </div>
        </div>
      ) : (
        <p className="empty" style={{ marginBottom: 20 }}>
          No named contact found on a public page. The system does not invent one.
          {person === undefined && " Use the Sales Navigator search from the company view."}
        </p>
      )}

      <p className="eyebrow">outreach draft</p>
      {mail ? (
        <div className="mail">
          <div className="mail-head">
            <span className="mail-subject">{mail.subject}</span>
            <span className={`verdict ${flags.length ? "flag" : "pass"}`}>
              {flags.length ? "needs review" : "checked"}
            </span>
          </div>
          <div className="mail-body">{mail.body}</div>
          {flags.length > 0 && (
            <div className="flagged">
              <strong>Blocked from sending.</strong> These claims are not supported
              by the evidence above:
              <ul>{flags.map((f, i) => <li key={i}>{f}</li>)}</ul>
            </div>
          )}
        </div>
      ) : (
        <p className="empty">No draft written for this lead.</p>
      )}
    </>
  );
}

function Ev({ label, s }) {
  if (!s) return null;
  return (
    <div className="ev-row">
      <span className="ev-label">{label}</span>
      <span className="ev-val">{String(s.value)}</span>
      {s.source?.url && (
        <a className="ev-src" href={s.source.url} target="_blank" rel="noreferrer">
          {host(s.source.url)}
        </a>
      )}
    </div>
  );
}
