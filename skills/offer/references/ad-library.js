// Run in a Meta Ad Library results page (read-only) with the browser's JavaScript tool.
// It returns the page's ads as plain text in the shape offer.py ads reads, with the buttons,
// player timers and repeated creatives taken out and each ad cut to its first lines plus every
// line that holds a price, a guarantee or a link. Save what it returns to ads-<n>.txt.
(() => {
  const noise = /^(active|inactive|platforms|eu transparency|open dropdown|see ad details|see summary details|categories|this ad has multiple versions|\d+ ads? uses? this creative and text|​|learn more|shop now|apply now|sign up|book now|watch more|see more|get offer|download|subscribe|contact us|send message|remove|\d+:\d+ \/ \d+:\d+(:\d+)?)$/i;
  const keepLine = /guarantee|refund|money.back|risk.free|[$€£]\s?\d|\d\s?(usd|eur|gbp)\b|^(https?:\/\/)?([a-z0-9-]+\.)+[a-z]{2,}(\/\S*)?$|https?:\/\//i;
  const lines = document.body.innerText.split("\n").map(s => s.trim()).filter(s => s && !noise.test(s));
  const ads = [];
  let cur = null;
  for (const s of lines) {
    if (/^Library ID:/.test(s)) { cur = { head: [s], body: [], open: true }; ads.push(cur); continue; }
    if (!cur) continue;
    if (cur.open) { cur.head.push(s); if (s === "Sponsored") cur.open = false; } else cur.body.push(s);
  }
  const seen = new Set();
  const out = [];
  for (const a of ads) {
    if (a.open) continue;
    const advertiser = a.head[a.head.length - 2] || "";
    const key = advertiser + "|" + a.body.join(" ").slice(0, 200);
    if (seen.has(key)) continue;
    seen.add(key);
    let used = 0;
    const kept = [];
    for (const s of a.body) {
      if (keepLine.test(s)) { kept.push(s.slice(0, 400)); continue; }
      if (used < 280) { kept.push(s.slice(0, 280 - used)); used += s.length; }
    }
    out.push(a.head.filter(h => /^(Library ID|Started running)/.test(h) || h === advertiser || h === "Sponsored").join("\n"));
    out.push(kept.join("\n"));
  }
  return out.join("\n");
})()
