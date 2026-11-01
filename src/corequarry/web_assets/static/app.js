"use strict";
const form = document.querySelector("#search-form");
const activity = document.querySelector("#activity");
const input = document.querySelector("#query");
let events = null, requestNumber = 0, fieldRequest = null;
const selected = () => [...form.querySelectorAll(".collection-choice:checked")].map(e => e.value);
const showError = error => { activity.className = "notice"; activity.textContent = error.message || error; };

async function checked(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : "The request could not be completed.");
  }
  return response;
}

async function updateFields(wanted = "") {
  if (fieldRequest) fieldRequest.abort();
  fieldRequest = new AbortController();
  const params = new URLSearchParams();
  selected().forEach(id => params.append("collection", id));
  const status = document.querySelector("#scope-status");
  if (!selected().length) { status.textContent = "Choose a collection"; return; }
  try {
    const fields = await (await checked(await fetch("/api/fields?" + params, {signal: fieldRequest.signal}))).json();
    const select = document.querySelector("#field");
    select.replaceChildren(new Option("All fields", ""), ...fields.map(f => new Option(f.name + " · " + f.datatype, f.name)));
    select.value = [...select.options].some(o => o.value === wanted) ? wanted : "";
    status.textContent = fields.length + " fields available";
    document.querySelector("#suggestions").replaceChildren();
  } catch (error) { if (error.name !== "AbortError") { status.textContent = "Fields unavailable"; showError(error); } }
}

function saveLocation(searchId, start = 0, replace = false) {
  const url = new URL(location.href);
  url.search = "";
  url.searchParams.set("q", input.value);
  selected().forEach(id => url.searchParams.append("collection", id));
  ["syntax", "field", "normalization"].forEach(id => url.searchParams.set(id, document.getElementById(id).value));
  url.searchParams.set("sid", searchId);
  url.searchParams.set("start", start);
  history[replace ? "replaceState" : "pushState"]({}, "", url);
}

function feedback(kind, ids) {
  if (!ids.length) return;
  navigator.sendBeacon("/api/events", new Blob([JSON.stringify({kind, result_ids: ids})], {type: "application/json"}));
}

async function loadPage(id, start = 0) {
  await htmx.ajax("GET", "/search/" + encodeURIComponent(id) + "?start=" + start, {source: "#workspace", target: "#workspace", swap: "innerHTML"});
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const number = ++requestNumber;
  if (events) events.close();
  htmx.trigger("#workspace", "htmx:abort");
  activity.className = "working"; activity.textContent = "Searching your collections…";
  try {
    const body = {query: input.value, collections: selected(), syntax: document.querySelector("#syntax").value,
      field: document.querySelector("#field").value, normalization: document.querySelector("#normalization").value};
    const job = await (await checked(await fetch("/api/search", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)}))).json();
    if (number !== requestNumber) return;
    events = new EventSource(job.events_url);
    events.onmessage = async message => {
      if (number !== requestNumber) return;
      const state = JSON.parse(message.data);
      if (state.status === "pending") return;
      events.close();
      if (state.status === "failed") { showError(state.error); return; }
      activity.textContent = ""; activity.className = "";
      saveLocation(state.search_id);
      await loadPage(state.search_id);
    };
    events.onerror = () => {
      if (number !== requestNumber) return;
      if (events.readyState === EventSource.CLOSED) showError("The search connection closed. Run the query again.");
      else { activity.className = "working"; activity.textContent = "Reconnecting to your search…"; }
    };
  } catch (error) { if (number === requestNumber) showError(error); }
});

form.addEventListener("change", event => {
  if (event.target.matches(".collection-choice")) updateFields(document.querySelector("#field").value);
  if (event.target.id === "field") htmx.trigger(input, "field-change");
});
document.querySelectorAll(".example").forEach(button => button.addEventListener("click", () => {
  input.value = button.dataset.query; document.querySelector("#syntax").value = "rpn"; input.focus();
}));
document.addEventListener("click", event => {
  const link = event.target.closest("a[data-result-id]");
  if (link) feedback("click", [link.dataset.resultId]);
});
document.body.addEventListener("htmx:afterSwap", async event => {
  if (event.detail.target.id !== "workspace") return;
  const results = document.querySelector(".results");
  if (!results) return;
  const recipe = JSON.parse(document.querySelector("#search-recipe").textContent);
  input.value = recipe.query;
  form.querySelectorAll(".collection-choice").forEach(e => { e.checked = recipe.collections.includes(e.value); });
  document.querySelector("#syntax").value = recipe.syntax;
  document.querySelector("#normalization").value = recipe.normalization;
  await updateFields(recipe.field);
  saveLocation(results.dataset.searchId, Number(results.dataset.start), true);
  feedback("impression", [...results.querySelectorAll("article[data-result-id]")].map(e => e.dataset.resultId));
});
document.body.addEventListener("htmx:responseError", event => {
  if (event.detail.target.id === "workspace") showError("This search expired or could not be loaded. Run the query again.");
});

async function restore() {
  const params = new URLSearchParams(location.search);
  if (params.has("q")) input.value = params.get("q");
  if (params.has("collection")) form.querySelectorAll(".collection-choice").forEach(e => { e.checked = params.getAll("collection").includes(e.value); });
  ["syntax", "normalization"].forEach(id => { if (params.has(id)) document.getElementById(id).value = params.get(id); });
  await updateFields(params.get("field") || "");
  if (params.has("sid")) await loadPage(params.get("sid"), Number(params.get("start") || 0));
}
window.addEventListener("popstate", restore);
restore();
