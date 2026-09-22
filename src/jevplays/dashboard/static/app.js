// Milestone 1: show the screen and the raw state. Milestone 2 adds the decision panel,
// party strip, and decision log.
const layout = new URLSearchParams(location.search).get("layout");
if (layout === "stream") document.body.dataset.layout = "stream";

const screen = document.getElementById("screen");
const status = document.getElementById("status");
const raw = document.getElementById("state");
const fields = {
  mode: document.getElementById("mode"),
  map: document.getElementById("map"),
  text: document.getElementById("text"),
  menu: document.getElementById("menu"),
  flags: document.getElementById("flags"),
};

const decisionEl = document.getElementById("decision");
const goalEl = document.getElementById("goal");
const legEl = document.getElementById("leg");
const logEl = document.getElementById("log");
const partyEl = document.getElementById("party");

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function pct(p) { return `${Math.round(p * 100)}%`; }

function renderChoice(id, q, a) {
  const box = el("div", `question${a.applied ? "" : " unused"}`);
  const head = el("div", "qhead");
  head.append(el("span", "qid", id), el("span", "badge", `confidence ${a.confidence.toFixed(2)}`));
  if (!a.applied) head.append(el("span", "badge na", "not used"));
  box.append(head, el("p", "instructions", q.instructions));
  const options = Object.entries(a.probabilities).sort((x, y) => y[1] - x[1]);
  for (const [name, p] of options) {
    const row = el("div", `bar${name === a.choice ? " winner" : ""}`);
    const fill = el("div", "fill");
    fill.style.width = pct(p);
    row.append(el("span", "label", name), fill, el("span", "value", pct(p)));
    box.append(row);
  }
  return box;
}

function renderNoul(id, q, a) {
  const box = el("div", `question${a.applied ? "" : " unused"}`);
  const head = el("div", "qhead");
  head.append(el("span", "qid", id));
  // `faint` is never applied by design -- it is scored against the game later, not acted on --
  // so the badge says what it is rather than reading as an option the policy passed over.
  if (!a.applied) head.append(el("span", "badge na", id === "faint" ? "prediction" : "not used"));
  box.append(head, el("p", "instructions", q.instructions));
  const row = el("div", "split");
  const yes = el("div", "yes", `yes ${pct(a.noul)}`);
  yes.style.width = pct(a.noul);
  const no = el("div", "no", `no ${pct(1 - a.noul)}`);
  no.style.width = pct(1 - a.noul);
  row.append(yes, no);
  box.append(row);
  return box;
}

function renderDecision(d) {
  decisionEl.replaceChildren();
  const action = el("div", "action", d.action);
  // Any recorded reason is worth showing, not just d.fallback: the never-nickname policy
  // decides without the model and is deliberately not a fallback, but the page should say so.
  if (d.fallback_reason) action.append(el("span", "badge fallback", `fallback: ${d.fallback_reason}`));
  decisionEl.append(action);
  for (const [id, q] of Object.entries(d.questions)) {
    const a = d.answers[id];
    if (!a) continue;
    decisionEl.append(a.primitive === "choice" ? renderChoice(id, q, a) : renderNoul(id, q, a));
  }
  // No model means code decided this one on its own, so there is no latency or token count to
  // show -- "· 0 ms · 0 tokens" would read as a measurement rather than an absence.
  if (d.model) {
    decisionEl.append(el("p", "meta", `${d.model} · ${d.latency_ms} ms · ${d.input_tokens} tokens`));
  }
  if (d.kind === "explore") {
    // The line shows the milestone the run is working towards, not the option just chosen:
    // the option is already in the log line below, and the milestone is what it is all for.
    goalEl.textContent = d.state_summary.milestone || d.action;
  }
  const top = d.answers.move ? ` (${d.answers.move.confidence.toFixed(2)})` : "";
  // An explore action already reads "explore: ...", so only the other kinds get the prefix.
  const headline = d.action.startsWith(`${d.kind}:`) ? d.action : `${d.kind}: ${d.action}`;
  const item = el("li", "", `${headline}${top}`);
  logEl.prepend(item);
  while (logEl.children.length > 50) logEl.lastChild.remove();
}

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

const TRY_AGAIN_LATER = 1013; // the server is at its viewer limit
let ws = null;

function connect() {
  if (document.hidden) return; // a retry that came due after the tab was hidden; shown reconnects
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const sock = new WebSocket(`${proto}://${location.host}/ws`);
  ws = sock;
  ws.onmessage = (msg) => {
    const event = JSON.parse(msg.data);
    if (event.type === "frame") {
      screen.src = `data:image/jpeg;base64,${event.jpeg}`;
    } else if (event.type === "state") {
      const s = event.state;
      fields.mode.textContent = s.mode;
      fields.map.textContent = `${s.map} (${s.tile[0]}, ${s.tile[1]})`;
      fields.text.textContent = s.text || "–";
      fields.menu.textContent = s.menu_items.length
        ? s.menu_items.map((item, i) => (i === s.cursor ? `▶${item}` : item)).join("  ")
        : "–";
      fields.flags.textContent = s.flags && s.flags.length ? s.flags.join(", ") : "–";
      raw.textContent = JSON.stringify(s, null, 2);
      renderParty(s.party || []);
    } else if (event.type === "status") {
      status.textContent = event.message ? `${event.status}: ${event.message}` : event.status;
      status.dataset.status = event.status;
      legEl.textContent = event.message || event.status;
      legEl.dataset.status = event.status;
      // The milestone the line names is done, so it is stale the moment this lands.
      if (/^milestone done[ :]/.test(event.message || "")) {
        goalEl.textContent = "–";
      }
    } else if (event.type === "decision") {
      renderDecision(event.decision);
    }
  };
  ws.onclose = (event) => {
    // Hidden: closed on purpose below, and it reconnects when shown. Superseded: a newer socket
    // already replaced this one, and retrying here too would leave two open.
    if (document.hidden || sock !== ws) return;
    const full = event.code === TRY_AGAIN_LATER;
    status.textContent = full ? "the demo is full, retrying…" : "disconnected, retrying…";
    status.dataset.status = "stopped";
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
