// Milestone 1: show the screen and the raw state. Milestone 2 adds the decision panel,
// party strip, and decision log.
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
  if (!a.applied) head.append(el("span", "badge na", "not used"));
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
  if (d.fallback) action.append(el("span", "badge fallback", `fallback: ${d.fallback_reason}`));
  decisionEl.append(action);
  for (const [id, q] of Object.entries(d.questions)) {
    const a = d.answers[id];
    if (!a) continue;
    decisionEl.append(a.primitive === "choice" ? renderChoice(id, q, a) : renderNoul(id, q, a));
  }
  decisionEl.append(el("p", "meta", `${d.model} · ${d.latency_ms} ms · ${d.input_tokens} tokens`));
  if (d.kind === "goal") {
    const id = (d.action.match(/^pursue (.+)$/) || [])[1];
    const goals = d.state_summary.goals || {};
    goalEl.textContent = (id && goals[id]) || d.action;
  }
  const top = d.answers.move ? ` (${d.answers.move.confidence.toFixed(2)})` : "";
  const item = el("li", "", `${d.kind}: ${d.action}${top}`);
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

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
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
      if (/^goal (done|blocked):/.test(event.message || "")) {
        goalEl.textContent = "–";
      }
    } else if (event.type === "decision") {
      renderDecision(event.decision);
    }
  };
  ws.onclose = () => {
    status.textContent = "disconnected, retrying…";
    status.dataset.status = "stopped";
    setTimeout(connect, 1000);
  };
}

connect();
