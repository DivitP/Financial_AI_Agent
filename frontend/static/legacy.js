"use strict";
document.querySelector("#researchForm").addEventListener("submit", event => {
  event.currentTarget.querySelector("button").disabled = true;
  document.querySelector("#researchStatus").hidden = false;
});
function appendText(parent, tag, text) {
  const node = document.createElement(tag);
  node.textContent = String(text ?? "");
  parent.append(node);
  return node;
}
document.querySelector("#askForm").addEventListener("submit", async event => {
  event.preventDefault();
  const container = document.querySelector("#answerContainer");
  container.replaceChildren();
  try {
    const response = await fetch("/api/ask", { method: "POST",
      headers: { "Content-Type": "application/json", "X-Requested-With": "FinancialAI" },
      body: JSON.stringify({ ticker: document.querySelector("#tickerHidden").value,
        question: document.querySelector("#questionInput").value }) });
    if (!response.ok) throw new Error("Request failed");
    const data = await response.json();
    appendText(container, "pre", data.answer);
    for (const source of data.sources ?? []) {
      if (typeof source !== "string" || /[\u0000-\u0020\u007f\\]/.test(source) || !/^https?:\/\//i.test(source)) continue;
      try {
        const url = new URL(source);
        if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) continue;
        const link = appendText(container, "a", source);
        link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
      } catch { /* Invalid source links are not interactive. */ }
    }
  } catch { appendText(container, "p", "Unable to answer. Please retry."); }
});
const task = document.body.dataset.taskId;
async function poll() {
  try {
    const response = await fetch("/api/chart-status/" + encodeURIComponent(task));
    if (!response.ok) throw new Error("Request failed");
    const data = await response.json();
    document.querySelector("#statusBar").textContent = data.current_step ?? data.status;
    if (data.status === "processing") { setTimeout(poll, 1500); return; }
    const container = document.querySelector("#chartsContainer");
    appendText(container, "pre", data.tech_text);
    for (const key of ["tech_image", "bollinger_image", "arima_image", "garch_image"]) {
      const value = data[key];
      if (typeof value !== "string" || value.length > 14000000 || !/^iVBORw0KGgo[A-Za-z0-9+/]*={0,2}$/.test(value)) continue;
      const image = document.createElement("img"); image.alt = key;
      image.src = "data:image/png;base64," + value; container.append(image);
    }
  } catch { document.querySelector("#statusBar").textContent = "Analysis unavailable. Please retry."; }
}
if (task) poll();
