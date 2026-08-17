// Score maths, mirrored from src/models.py.
//
// The frontend recomputes totals from raw component levels rather than
// reading a precomputed score, which is what lets the weight sliders work:
// the model's judgement is fixed, the weighting is not. That is the same
// separation the pipeline makes, so the numbers here and there agree.

export function scoreOf(components, overrides) {
  if (!components || components.length === 0) return 0;
  let total = 0;
  let weight = 0;
  for (const c of components) {
    const w = overrides && c.name in overrides ? overrides[c.name] : c.weight;
    total += c.raw * w;
    weight += w;
  }
  return weight > 0 ? (100 * total) / weight : 0;
}

export function quadrantOf(fit, lev) {
  if (fit >= 60 && lev >= 60) return "call now";
  if (fit >= 60) return "displacement";
  return lev >= 60 ? "low priority" : "hold";
}

export function tierOf(fit) {
  return fit >= 70 ? "A" : fit >= 60 ? "B" : "C";
}

// How much of what we believe about a company is actually sourced. Drives
// the ring fill: a hollow ring is a lead we know little about, which is a
// different thing from a lead that scored badly.
export function coverageOf(lead) {
  const c = lead.company || {};
  const singles = [
    c.website, c.hq_city, c.hq_country, c.revenue_usd, c.revenue_band,
    c.employees, c.employees_band,
  ].filter(Boolean).length;
  const lists = (c.product_lines || []).length + (c.recent_signals || []).length;
  const people = (lead.stakeholders || []).length;
  return Math.min(1, (singles + Math.min(lists, 5) + people * 2) / 12);
}

export function money(c) {
  if (c.revenue_usd) {
    const v = c.revenue_usd.value;
    if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
    if (v >= 1e6) return `$${Math.round(v / 1e6)}M`;
    return `$${v.toLocaleString()}`;
  }
  if (c.revenue_band) return c.revenue_band.value;
  return "size unknown";
}

export function host(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "source";
  }
}
