// The page is a stage with two sides: the game on the left (code executes) and Jev on the
// right (judges). It renders what the loop publishes and nothing else; the words for a decision
// come from the `view` the server attaches to each decision event (dashboard/present.py).
const params = new URLSearchParams(location.search);
if (params.get("layout") === "stream") document.body.dataset.layout = "stream";
if (params.has("debug")) document.getElementById("debug").hidden = false;

const screen = document.getElementById("screen");
const status = document.getElementById("status");
const overlay = document.getElementById("overlay");
const overlayText = document.getElementById("overlay-text");
const activityEl = document.getElementById("activity");
const noteEl = document.getElementById("note");
const goalEl = document.getElementById("goal");
const decisionEl = document.getElementById("decision");
const logEl = document.getElementById("log");
const partyEl = document.getElementById("party");
const raw = document.getElementById("state");
const fields = {
  mode: document.getElementById("mode"),
  map: document.getElementById("map"),
  text: document.getElementById("text"),
  menu: document.getElementById("menu"),
  flags: document.getElementById("flags"),
};

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function pct(p) { return `${Math.round((p || 0) * 100)}%`; }

// -- the run's state: the pill and the overlay over the screen ------------------------------

const PILL = {
  connecting: "connecting",
  running: "live",
  waiting_for_api: "waiting for API",
  paused: "stuck",
  unwatched: "waking up",
  resting: "resting",
  stopped: "ended",
  finished: "finished",
  reconnecting: "reconnecting",
  full: "demo full",
  replay: "replay",
};

let replay = null; // {stamp, i, n, done} once a replay status has been seen
let gotFrame = false;

function overlayFor(st, message) {
  switch (st) {
    case "running": return replay ? replayText() : (gotFrame ? null : "Connecting…");
    case "connecting": return "Connecting…";
    case "unwatched": return "The game paused while nobody was watching. It is waking up for you.";
    case "resting": return "Today's decision budget is spent. The run rests until 00:00 UTC.";
    case "waiting_for_api":
    case "paused": return message || PILL[st];
    case "stopped":
      if (replay) return `${replayText()} ${message || ""}`.trim();
      return `The run ended${message ? `: ${message}` : "."} The page reconnects by itself when the next one starts.`;
    case "finished": return message || "Finished.";
    case "reconnecting": return "Reconnecting…";
    case "full": return "The demo is serving as many viewers as it can. Trying again in 30 seconds.";
    default: return message || st;
  }
}

function replayText() {
  if (!replay) return "";
  const where = replay.done ? `finished, ${replay.n} decisions` : `decision ${replay.i} of ${replay.n}`;
  return `Replay of run ${replay.stamp}, ${where}. The log kept Jev's decisions, not the video.`;
}

function setStatus(st, message) {
  const shown = st === "running" && replay ? "replay" : st;
  status.textContent = PILL[shown] || shown;
  status.dataset.status = shown;
  const text = overlayFor(st, message);
  overlay.hidden = text === null;
  overlay.dataset.status = shown;
  overlayText.textContent = text || "";
  document.body.classList.toggle("replay", Boolean(replay));
}

const HOUSEKEEPING = [/^checkpoint (\d+)$/, /^someone is watching$/];

function setActivity(st, message) {
  if (st === "unwatched") {
    // The viewer reading this is the one who woke it, so the loop's message would be wrong.
    activityEl.textContent = "paused while nobody was watching; waking up";
    noteEl.hidden = true;
    return;
  }
  const m = HOUSEKEEPING.map((re) => message.match(re)).find(Boolean);
  if (m) {
    noteEl.textContent = m[1] ? `saved checkpoint ${m[1]}` : "";
    noteEl.hidden = !m[1];
    return;
  }
  if (message) {
    activityEl.textContent = message;
    noteEl.hidden = true;
  }
}

function onStatus(event) {
  const message = event.message || "";
  const m = message.match(/^replaying (\S+): (\d+)\/(\d+)$/);
  if (m) replay = { stamp: m[1], i: Number(m[2]), n: Number(m[3]), done: false };
  const done = message.match(/^replayed (\d+) decisions$/);
  if (done && replay) replay = { ...replay, n: Number(done[1]), done: true };
  setStatus(event.status, message);
  setActivity(event.status, message);
  // The milestone the line names is done, so it is stale the moment this lands.
  if (/^milestone done[ :]/.test(message)) goalEl.textContent = "–";
}

// -- the Jev card ------------------------------------------------------------------------------

function tag(text, cls = "") { return el("span", `tag ${cls}`.trim(), text); }

function choiceRows(q) {
  const long = q.options.some((o) => o.label.length > 28);
  const box = el("div", `rows${long ? " long" : ""}`);
  for (const o of q.options) {
    const row = el("div", `row${o.chosen ? " chosen" : ""}`);
    const label = el("span", "olabel");
    label.append(el("span", "oname", (o.chosen ? "✓ " : "") + o.label));
    if (o.memory) label.append(" ", tag(o.memory, "mem"));
    const bar = el("span", "bar");
    const fill = el("span", "fill");
    fill.style.width = pct(o.p);
    bar.append(fill);
    row.append(label, bar, el("span", "val", pct(o.p)));
    box.append(row);
  }
  return box;
}

function splitBar(q) {
  const row = el("div", "split");
  const bar = el("span", "bar");
  const fill = el("span", "fill");
  fill.style.width = pct(q.yes);
  bar.append(fill);
  row.append(el("span", "val yes", `yes ${pct(q.yes)}`), bar, el("span", "val no", `no ${pct(1 - q.yes)}`));
  return row;
}

function questionBlock(q, { showRole }) {
  const box = el("div", `q ${q.role}`);
  const head = el("div", "qhead");
  head.append(el("span", "qlabel", q.label));
  if (q.role === "prediction") head.append(tag("prediction"));
  else if (q.role === "unused") head.append(tag("not used"));
  else if (showRole) head.append(tag("acted on", "on"));
  if (q.primitive === "choice" && q.confidence !== undefined && q.confidence !== null) {
    head.append(el("span", "chip", `confidence ${Number(q.confidence).toFixed(2)}`));
  }
  box.append(head, q.primitive === "choice" ? choiceRows(q) : splitBar(q));
  return box;
}

// An unused question in one phrase: its top option, or which way the yes/no went.
function brief(q) {
  if (q.primitive === "choice") {
    const top = q.options[0];
    return top ? `${q.label} ${top.label} ${pct(top.p)}` : q.label;
  }
  const yes = q.yes >= 0.5;
  return `${q.label} ${yes ? "yes" : "no"} ${pct(yes ? q.yes : 1 - q.yes)}`;
}

function alsoAsked(questions, label) {
  const line = el("div", `also ${label === "prediction" ? "prediction" : ""}`.trim());
  line.append(el("span", "k", label));
  for (const q of questions) {
    const d = el("details", "brief");
    d.append(el("summary", "", brief(q)), questionBlock(q, { showRole: false }));
    line.append(d);
  }
  return line;
}

let lastCardAt = 0;

function renderCard(d, view) {
  decisionEl.replaceChildren();
  decisionEl.classList.remove("empty", "is-new");
  // The arrival animation marks a decision landing while the game plays; in an unpaced run
  // (a recording, a measurement) decisions come faster than it, so every bar would be caught
  // half-grown. A card that follows another within a second arrives still.
  const now = performance.now();
  if (now - lastCardAt > 1000) {
    void decisionEl.offsetWidth; // restart the arrival animation
    decisionEl.classList.add("is-new");
  }
  lastCardAt = now;

  const where = el("div", "where");
  where.append(tag(view.actor === "code" ? "code" : view.kind, `kind ${view.actor}`));
  if (view.where) where.append(el("span", "where-text", view.where));
  const ago = el("span", "ago");
  ago.dataset.ts = d.ts;
  where.append(ago);
  decisionEl.append(where);

  const applied = view.questions.filter((q) => q.role === "applied");
  const unused = view.questions.filter((q) => q.role === "unused");
  const predictions = view.questions.filter((q) => q.role === "prediction");
  for (const q of applied) decisionEl.append(questionBlock(q, { showRole: view.questions.length > 1 }));
  if (unused.length) decisionEl.append(alsoAsked(unused, "also asked"));
  if (predictions.length) decisionEl.append(alsoAsked(predictions, "prediction"));

  const handoff = el("div", "handoff");
  handoff.append(el("span", "arrow", "→ "), el("span", "", view.handoff));
  if (view.actor === "code") {
    handoff.append(" ", el("span", "reason", view.reason ? `(decided on its own: ${view.reason})` : "(decided on its own)"));
  } else if (view.reason) {
    handoff.append(" ", el("span", "reason", `(${view.reason})`));
  }
  decisionEl.append(handoff);

  const meta = el("div", "meta");
  if (d.model) meta.append(el("span", "mono", `${d.model} · ${d.latency_ms} ms · ${d.input_tokens} tokens`));
  const asked = view.questions.filter((q) => q.instructions);
  if (asked.length) {
    const details = el("details", "asked");
    details.append(el("summary", "", "the question as Jev saw it"));
    const dl = el("dl");
    for (const q of asked) dl.append(el("dt", "mono", q.id), el("dd", "", q.instructions));
    details.append(dl);
    meta.append(details);
  }
  decisionEl.append(meta);
  tickAgo();
}

function logItem(d, view) {
  const item = el("li");
  item.append(el("span", "summary", view.summary), tag(view.actor === "code" ? "code" : view.kind, `kind ${view.actor}`));
  return item;
}

let cardTs = null;

function onDecision(event) {
  const d = event.decision;
  const view = event.view;
  if (!view) return; // an older server; nothing to render from
  if (view.goal) goalEl.textContent = view.goal;
  if (cardTs === null || d.ts >= cardTs) {
    cardTs = d.ts;
    renderCard(d, view);
    logEl.prepend(logItem(d, view));
  } else {
    logEl.append(logItem(d, view)); // older than the card: a late joiner being caught up
  }
  while (logEl.children.length > 50) logEl.lastChild.remove();
}

// -- "4s ago" ------------------------------------------------------------------------------------
// A decision's ts is the server's clock; the offset to ours is taken from the newest decision,
// never negative, so the card is never "in the future". Hidden on a replay, whose decisions
// are days old.
let offset = null;

function tickAgo() {
  for (const node of document.querySelectorAll(".ago")) {
    const ts = Number(node.dataset.ts);
    if (replay || !ts) { node.textContent = ""; continue; }
    if (offset === null || ts > cardTs - 1e-9) offset = Math.max(0, Date.now() / 1000 - ts);
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts - offset));
    node.textContent = s < 60 ? `${s}s ago` : `${Math.floor(s / 60)}m ago`;
  }
}
setInterval(tickAgo, 1000);

// -- the game side -------------------------------------------------------------------------------

function hpClass(hp, max) {
  const f = max ? hp / max : 0;
  return f > 0.6 ? "hp-healthy" : f > 0.3 ? "hp-hurt" : f > 0.1 ? "hp-low" : "hp-critical";
}

function renderParty(party) {
  partyEl.replaceChildren();
  for (const mon of party) {
    const card = el("div", "mon");
    card.append(el("div", "name", `${mon.nickname} L${mon.level}`));
    const bar = el("div", "hpbar");
    const fill = el("div", `hpfill ${hpClass(mon.hp, mon.max_hp)}`);
    fill.style.width = mon.max_hp ? pct(mon.hp / mon.max_hp) : "0%";
    bar.append(fill);
    card.append(bar, el("div", "hp", `${mon.hp}/${mon.max_hp}${mon.status !== "none" ? " · " + mon.status : ""}`));
    partyEl.append(card);
  }
}

function onState(s) {
  fields.mode.textContent = s.mode;
  fields.map.textContent = `${s.map} (${s.tile[0]}, ${s.tile[1]})`;
  fields.text.textContent = s.text || "–";
  fields.menu.textContent = s.menu_items.length
    ? s.menu_items.map((item, i) => (i === s.cursor ? `▶${item}` : item)).join("  ")
    : "–";
  fields.flags.textContent = s.flags && s.flags.length ? s.flags.join(", ") : "–";
  raw.textContent = JSON.stringify(s, null, 2);
  renderParty(s.party || []);
}

// -- the socket --------------------------------------------------------------------------------

const TRY_AGAIN_LATER = 1013; // the server is at its viewer limit
let ws = null;
let lastStatus = null;

function connect() {
  if (document.hidden) return; // a retry that came due after the tab was hidden; shown reconnects
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const sock = new WebSocket(`${proto}://${location.host}/ws`);
  ws = sock;
  ws.onmessage = (msg) => {
    const event = JSON.parse(msg.data);
    if (event.type === "frame") {
      screen.src = `data:image/jpeg;base64,${event.jpeg}`;
      if (!gotFrame) {
        gotFrame = true;
        if (lastStatus) setStatus(lastStatus.status, lastStatus.message || "");
      }
    } else if (event.type === "state") {
      onState(event.state);
    } else if (event.type === "status") {
      lastStatus = event;
      onStatus(event);
    } else if (event.type === "decision") {
      onDecision(event);
    }
  };
  ws.onclose = (event) => {
    // Hidden: closed on purpose below, and it reconnects when shown. Superseded: a newer socket
    // already replaced this one, and retrying here too would leave two open.
    if (document.hidden || sock !== ws) return;
    const full = event.code === TRY_AGAIN_LATER;
    setStatus(full ? "full" : "reconnecting", "");
    setTimeout(connect, full ? 30000 : 1000);
  };
}

// A tab nobody can see is not watching: let the socket go so the run can pause (a background
// tab left open overnight would otherwise keep it playing), and pick it back up when shown.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (ws) ws.close();
  } else if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
    connect();
  }
});

connect();
