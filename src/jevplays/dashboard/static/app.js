// Milestone 1: show the screen and the raw state. The decision panel arrives with milestone 2.
const screen = document.getElementById("screen");
const status = document.getElementById("status");
const raw = document.getElementById("state");
const fields = {
  mode: document.getElementById("mode"),
  map: document.getElementById("map"),
  text: document.getElementById("text"),
  menu: document.getElementById("menu"),
};

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
      raw.textContent = JSON.stringify(s, null, 2);
    } else if (event.type === "status") {
      status.textContent = event.message ? `${event.status}: ${event.message}` : event.status;
      status.dataset.status = event.status;
    }
  };
  ws.onclose = () => {
    status.textContent = "disconnected, retrying…";
    status.dataset.status = "stopped";
    setTimeout(connect, 1000);
  };
}

connect();
