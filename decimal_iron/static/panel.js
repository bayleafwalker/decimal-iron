(() => {
  const $ = (id) => document.getElementById(id);
  const linkState = $("link-state");
  const digits = $("digit-display");
  const members = $("member-select");

  async function post(action, fields = {}) {
    const response = await fetch("/panel/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...fields }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || data.error || "panel control failed");
    return data;
  }

  function showDigits(snapshot) {
    digits.replaceChildren();
    const text = snapshot.display.digits;
    const masks = snapshot.display.segments;
    for (let index = 0; index < text.length; index += 1) {
      const glyph = document.createElement("span");
      glyph.className = "digit";
      for (let segment = 0; segment < 7; segment += 1) {
        const part = document.createElement("i");
        part.className = "segment" + ((masks[index] & (1 << segment)) ? " lit" : "");
        glyph.append(part);
      }
      digits.append(glyph);
    }
    $("register-value").textContent = String(snapshot.display.value);
    $("register-meta").textContent = `${snapshot.selector.register} · ${snapshot.display.width} DIGITS`;
  }

  function showMemory(snapshot) {
    const window = $("wordmark-window");
    window.replaceChildren();
    for (const cell of snapshot.wordmark_window) {
      const element = document.createElement("span");
      element.className = "memory-cell" + (cell.wordmark ? " marked" : "");
      element.title = `address ${cell.address}; word mark ${cell.wordmark ? "set" : "clear"}`;
      element.append(document.createTextNode(cell.character));
      const address = document.createElement("small");
      address.textContent = String(cell.address).padStart(3, "0");
      element.append(address);
      window.append(element);
    }
    $("memory-label").textContent = `AR ${String(snapshot.registers.AR).padStart(3, "0")}`;
  }

  function setLamp(id, on) { $(id).classList.toggle("on", Boolean(on)); }

  function render(snapshot) {
    linkState.textContent = "LIVE";
    linkState.className = "connected";
    const state = snapshot.processor;
    const cpu = snapshot.registers;
    $("day-key").value = state.key_position;
    $("register-select").value = snapshot.selector.register;
    $("business-date").textContent = state.business_date;
    $("phase-key").textContent = `${state.phase} / ${state.key_position}`;
    $("last-instruction").textContent = cpu.last_instruction;
    $("cycle-count").textContent = `${cpu.instruction_count} / ${cpu.alu_digit_cycles}`;
    $("journal-count").textContent = String(state.journal_events);
    setLamp("lamp-zero", cpu.zero);
    setLamp("lamp-negative", cpu.negative);
    setLamp("lamp-carry", cpu.carry);
    setLamp("lamp-overflow", cpu.overflow);
    setLamp("lamp-halted", cpu.halted);
    setLamp("lamp-beacon", state.beacon_on);
    showDigits(snapshot);
    showMemory(snapshot);
    const meter = snapshot.meter;
    if (![...members.options].some((item) => item.value === meter.member)) {
      const option = document.createElement("option"); option.value = meter.member; option.textContent = meter.member; members.append(option);
    }
    members.value = meter.member;
    $("meter-needle").style.transform = `rotate(${meter.deflection_percent * 0.8}deg)`;
    const minor = meter.value_minor;
    const sign = minor < 0 ? "-" : "";
    const magnitude = Math.abs(minor);
    $("meter-value").textContent = `${sign}${Math.floor(magnitude / 100).toLocaleString("en-US")}.${String(magnitude % 100).padStart(2, "0")} FIM`;
  }

  async function refresh() {
    try {
      const response = await fetch("/panel/state", { cache: "no-store" });
      if (!response.ok) throw new Error("panel read failed");
      render(await response.json());
    } catch (error) {
      linkState.textContent = "OFFLINE";
      linkState.className = "failed";
      $("service-result").textContent = error.message;
    }
  }

  $("day-key").addEventListener("change", async (event) => {
    try { render((await post("key", { position: event.target.value })).snapshot); }
    catch (error) { $("service-result").textContent = error.message; }
  });
  $("register-select").addEventListener("change", async (event) => {
    try { render((await post("register", { register: event.target.value })).snapshot); }
    catch (error) { $("service-result").textContent = error.message; }
  });
  members.addEventListener("change", async (event) => {
    try { render((await post("meter", { member: event.target.value })).snapshot); }
    catch (error) { $("service-result").textContent = error.message; }
  });
  $("examine-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await post("examine", { address: Number($("examine-address").value) });
      $("service-result").textContent = `EXAMINE ${String(result.cell.address).padStart(3,"0")} = ${result.cell.character} · WM ${result.cell.wordmark ? "ON" : "OFF"}`;
    } catch (error) { $("service-result").textContent = error.message; }
  });
  $("deposit-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await post("deposit", { address: Number($("deposit-address").value), character: Number($("deposit-character").value) });
      render(result.snapshot);
      $("service-result").textContent = "DIAGNOSTIC SCRATCH CELL UPDATED";
    } catch (error) { $("service-result").textContent = error.message; }
  });

  refresh();
  window.setInterval(refresh, 500);
})();
