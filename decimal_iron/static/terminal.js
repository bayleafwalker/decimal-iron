(() => {
  const ROWS = 24;
  const COLS = 80;
  const screen = document.getElementById("screen");
  const keyboard = document.getElementById("keyboard");
  const connection = document.getElementById("connection");
  const cursorState = document.getElementById("cursor-state");
  const cells = Array(ROWS * COLS).fill(" ");
  let row = 0;
  let column = 0;
  let escape = "";
  let socket;

  function draw() {
    const lines = [];
    for (let r = 0; r < ROWS; r += 1) lines.push(cells.slice(r * COLS, (r + 1) * COLS).join(""));
    screen.textContent = lines.join("\n");
  }

  function consume(bytes) {
    for (const byte of bytes) {
      if (escape) {
        escape += String.fromCharCode(byte);
        if (escape.length > 16) { escape = ""; continue; }
        if (/[A-Za-z]$/.test(escape)) {
          const match = /^\x1b\[([0-9;?]*)([A-Za-z])$/.exec(escape);
          if (!match) { escape = ""; continue; }
          const [, params, command] = match;
          if (command === "J" && params === "2") {
            cells.fill(" "); row = column = 0;
          } else if (command === "H") {
            const [r = "1", c = "1"] = params ? params.split(";") : [];
            row = Math.max(0, Math.min(ROWS - 1, Number(r) - 1));
            column = Math.max(0, Math.min(COLS - 1, Number(c) - 1));
          } else if (command === "K" && (params === "" || params === "0")) {
            const start = row * COLS + column;
            cells.fill(" ", start, (row + 1) * COLS);
          }
          escape = "";
        }
        continue;
      }
      if (byte === 0x1b) { escape = "\x1b"; continue; }
      if (byte >= 0x20 && byte <= 0x7e && row < ROWS && column < COLS) {
        cells[row * COLS + column] = String.fromCharCode(byte);
        column += 1;
        if (column === COLS) column = COLS - 1;
      }
    }
    draw();
  }

  function send(bytes) {
    if (socket && socket.readyState === WebSocket.OPEN) socket.send(Uint8Array.from(bytes));
  }

  function connect() {
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${scheme}//${location.host}/terminal`);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      connection.textContent = "CONNECTED";
      connection.className = "connected";
      cursorState.textContent = "CURSOR ACQUIRED";
      keyboard.focus();
    };
    socket.onmessage = (event) => {
      if (!(event.data instanceof ArrayBuffer)) return;
      consume(new Uint8Array(event.data));
    };
    socket.onclose = () => {
      connection.textContent = "DISCONNECTED";
      connection.className = "failed";
      cursorState.textContent = "RECONNECTING";
      window.setTimeout(connect, 1200);
    };
    socket.onerror = () => {
      connection.textContent = "CONNECTION ERROR";
      connection.className = "failed";
    };
  }

  keyboard.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); send([0x0d]); }
    else if (event.key === "Backspace") { event.preventDefault(); send([0x7f]); }
    else if (event.key === "Tab") { event.preventDefault(); send([0x09]); }
  });
  keyboard.addEventListener("beforeinput", (event) => {
    if (event.inputType === "insertText" && event.data) {
      event.preventDefault();
      const bytes = [];
      for (const character of event.data) {
        const code = character.codePointAt(0);
        if (code >= 0x20 && code <= 0x7e) bytes.push(code);
      }
      if (bytes.length) send(bytes);
    }
    if (event.inputType === "deleteContentBackward") event.preventDefault();
  });
  document.querySelector(".console-shell").addEventListener("click", () => keyboard.focus());
  connect();
})();
