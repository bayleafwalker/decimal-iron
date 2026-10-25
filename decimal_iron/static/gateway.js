const byId = (id) => document.getElementById(id);

function cell(row, value, className = "") {
  const item = document.createElement("td");
  item.textContent = value == null ? "—" : String(value);
  if (className) item.className = className;
  row.append(item);
}

function renderPayments(payments) {
  const body = byId("rows");
  body.replaceChildren();
  byId("count").textContent = `${payments.length} records`;
  if (!payments.length) {
    const row = document.createElement("tr");
    const empty = document.createElement("td");
    empty.colSpan = 5;
    empty.className = "empty";
    empty.textContent = "No payment requests yet.";
    row.append(empty);
    body.append(row);
    return;
  }
  for (const payment of payments) {
    const row = document.createElement("tr");
    cell(row, payment.payment_id);
    const statusCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `state ${payment.status}`;
    badge.textContent = payment.status;
    statusCell.append(badge);
    row.append(statusCell);
    cell(row, payment.receipt?.journal_sequence);
    const layers = payment.protocol?.layers?.map((layer) => layer.name) ?? [];
    cell(row, layers.join(" → "), "route");
    cell(row, payment.error, "details");
    body.append(row);
  }
}

async function refresh() {
  try {
    const [healthResponse, readyResponse, paymentsResponse] = await Promise.all([
      fetch("/healthz", { cache: "no-store" }),
      fetch("/readyz", { cache: "no-store" }),
      fetch("/payments?limit=50", { cache: "no-store" }),
    ]);
    const health = await healthResponse.json();
    const ready = await readyResponse.json();
    const result = await paymentsResponse.json();
    byId("health").textContent = health.status.toUpperCase();
    byId("phase").textContent = ready.processor_phase ?? ready.status.toUpperCase();
    byId("queue").textContent = `${health.queue_depth} queued / ${health.max_queue} max`;
    byId("updated").textContent = new Date().toLocaleTimeString();
    renderPayments(result.payments);
  } catch (error) {
    byId("health").textContent = "OFFLINE";
    byId("phase").textContent = "UNKNOWN";
    byId("updated").textContent = "—";
  }
}

refresh();
window.setInterval(refresh, 2000);
