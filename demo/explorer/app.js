/* Urbanium Twin Explorer: a static client for urbanium.twin-snapshot/1. */
"use strict";

const SNAPSHOT_SCHEMA = "urbanium.twin-snapshot/1";
const INDEX_SCHEMA = "urbanium.twin-index/1";
const DATA = "data/";

const QUANTITY = {
  air_temperature: { label: "Lufttemperatur", unit: "°C", short: "°" },
  water_level: { label: "Wasserstand", unit: "cm", short: " cm" },
};
const CAPABILITY = {
  weather: "Wetter",
  river_level: "Wasserstand",
  realtime_transport: "Nahverkehr in Echtzeit",
  open_data_catalog: "Open-Data-Katalog",
};
const ENTITY_KIND = {
  weather_station: "Wetterstation",
  river_gauge: "Pegel",
  water_body: "Gewässer",
  discovery_area: "Suchgebiet",
};
const SUPPORT = {
  configured: "konfiguriert",
  candidate: "wird geprüft",
  unknown: "ungeklärt",
  unavailable: "nicht verfügbar",
};
const AVAILABILITY = { available: "liefert Daten", degraded: "liefert teilweise", unavailable: "liefert keine Daten" };
const FRESHNESS = { fresh: "aktuell", stale: "veraltet", no_data: "keine Daten", last_known: "zuletzt bekannt" };
const PREDICATE = {
  located_in: "liegt im Suchgebiet",
  on_water_body: "misst am Gewässer",
  nearest_weather_station: "nächste Wetterstation",
};
const INVERSE = {
  located_in: "enthält",
  on_water_body: "gemessen von Pegel",
  nearest_weather_station: "nächster Pegel dazu",
};
const ATTRIBUTE = {
  station_id: "Stationskennung",
  elevation_m: "Höhe",
  state: "Bundesland",
  inventory_until: "Im Inventar bis",
  uuid: "PEGELONLINE-UUID",
  number: "Pegelnummer",
  water: "Gewässer",
  agency: "Zuständiges Amt",
  river_km: "Flusskilometer",
  gauge_zero_m: "Pegelnullpunkt",
};
const PROBLEM = {
  insufficient_aligned_stations: "Zu wenige Stationen mit gemeinsamem Messzeitpunkt. Für einen fairen Vergleich braucht es mindestens drei.",
  weather_unavailable: "Die Wetterquelle hat in diesem Lauf keine Daten geliefert.",
  river_level_unavailable: "Die Pegelquelle hat in diesem Lauf keine Daten geliefert.",
  trend_not_determinable: "Für einige Pegel fehlt ein Messwert von vor etwa sechs Stunden.",
  source_degraded: "Die Quelle hat nur teilweise geliefert.",
  mixed_units: "Die Werte kommen in unterschiedlichen Einheiten.",
};
const TREND = { rising: "steigt", falling: "fällt", steady: "gleichbleibend", unknown: "kein Vergleichswert" };
const TREND_ARROW = { rising: "▲", falling: "▼", steady: "▶", unknown: "" };

const state = {
  index: null,
  twin: null,
  cityId: null,
  view: "map",
  selected: null,
  hidden: new Set(),
  map: null,
  markers: new Map(),
  overlays: null,
};

/* Helpers ---------------------------------------------------------- */

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function svg(tag, attrs, ...children) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function esc(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function num(value, digits) {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString("de-DE", digits === undefined ? { maximumFractionDigits: 2 } : { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function signed(value) {
  const n = Number(value);
  return (n > 0 ? "+" : n < 0 ? "−" : "±") + num(Math.abs(n));
}

function timeFormat(options) {
  const zone = state.twin ? state.twin.city.timezone : "Europe/Berlin";
  return new Intl.DateTimeFormat("de-DE", { timeZone: zone, ...options });
}
const clock = (iso) => timeFormat({ hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
const dateTime = (iso) => timeFormat({ day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));

function valueText(entity, withUnit = true) {
  if (!entity.latest) return "–";
  const q = QUANTITY[entity.latest.quantity_id];
  const digits = entity.latest.quantity_id === "air_temperature" ? 1 : 0;
  const text = num(entity.latest.value, digits);
  return withUnit && q ? text + q.short : text;
}

/* Diverging temperature scale, fixed so cities stay comparable. */
const RAMP = [[-10, [44, 95, 138]], [0, [91, 155, 200]], [10, [233, 228, 207]], [20, [224, 138, 74]], [30, [178, 58, 42]]];
function tempColor(value) {
  const v = Math.max(-10, Math.min(30, Number(value)));
  for (let i = 1; i < RAMP.length; i++) {
    const [x1, c1] = RAMP[i];
    const [x0, c0] = RAMP[i - 1];
    if (v <= x1) {
      const t = (v - x0) / (x1 - x0);
      return `rgb(${c0.map((c, k) => Math.round(c + (c1[k] - c) * t)).join(",")})`;
    }
  }
  return "rgb(178,58,42)";
}

function entityById(id) {
  return state.twin.entities.find((e) => e.id === id) || null;
}

function agent(id) {
  return state.twin.agents.find((a) => a.component_id === id) || null;
}

function payload(run) {
  return run && run.run && run.run.outputs.length ? run.run.outputs[0].payload : null;
}

function trendFor(entityId) {
  const out = payload(agent("water_level_trend"));
  return out ? out.gauges.find((g) => g.entity === entityId) || null : null;
}

function sourceOf(sourceId) {
  return state.twin.city.sources.find((s) => s.id === sourceId) || null;
}

/* Loading ---------------------------------------------------------- */

async function fetchJson(path) {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

function showNotice(text, kind) {
  const notice = document.getElementById("notice");
  notice.textContent = text;
  notice.className = "notice" + (kind ? " " + kind : "");
  notice.hidden = !text;
}

async function start() {
  bindViewButtons();
  try {
    state.index = await fetchJson(DATA + "index.json");
  } catch (error) {
    showNotice("Die Twin-Daten fehlen. Lokal erzeugen mit: urbanium-twin build --out demo/explorer/data", "error");
    return;
  }
  if (state.index.schema_id !== INDEX_SCHEMA || !state.index.cities.length) {
    showNotice("Die Twin-Daten haben ein unbekanntes Format oder enthalten keine Stadt.", "error");
    return;
  }
  if (state.index.data_mode === "synthetic") {
    showNotice("Beispieldaten: Diese Werte sind erfunden und zeigen nur, wie der Explorer funktioniert. Es sind keine echten Messungen.");
  } else if (state.index.data_mode === "replay") {
    showNotice("Aufzeichnung: echte Messwerte, aber nicht live. Stand siehe oben rechts.");
  }
  renderCitySwitch();
  const params = new URLSearchParams(location.search);
  const wanted = params.get("city");
  const first = state.index.cities.find((c) => c.id === wanted) || state.index.cities.find((c) => c.id === "berlin") || state.index.cities[0];
  const view = params.get("view");
  if (["map", "graph", "compare"].includes(view)) state.view = view;
  await loadCity(first.id);
}

async function loadCity(cityId) {
  let twin;
  try {
    twin = await fetchJson(DATA + encodeURIComponent(cityId) + ".json");
  } catch (error) {
    showNotice(`Die Daten für diese Stadt konnten nicht geladen werden (${error.message}).`, "error");
    return;
  }
  if (twin.schema_id !== SNAPSHOT_SCHEMA) {
    showNotice("Der Snapshot dieser Stadt hat ein unbekanntes Format.", "error");
    return;
  }
  state.twin = twin;
  state.cityId = cityId;
  state.selected = null;
  for (const button of document.querySelectorAll("#cities button")) {
    button.setAttribute("aria-pressed", String(button.dataset.city === cityId));
  }
  syncUrl();
  document.title = `${twin.city.name}: Urbanium Twin Explorer`;
  document.getElementById("stamp").textContent = `Stand ${timeFormat({ day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(twin.generated_at))}`;
  document.getElementById("turtle-link").href = DATA + encodeURIComponent(cityId) + ".ttl";
  renderLayers();
  renderInsights();
  renderCredits();
  renderDetail();
  setView(state.view, { force: true });
}

function syncUrl() {
  const params = new URLSearchParams();
  params.set("city", state.cityId);
  if (state.view !== "map") params.set("view", state.view);
  history.replaceState(null, "", "?" + params.toString());
}

/* Header ----------------------------------------------------------- */

function renderCitySwitch() {
  const nav = document.getElementById("cities");
  nav.replaceChildren(
    ...state.index.cities.map((city) =>
      h("button", { type: "button", "data-city": city.id, "aria-pressed": "false", onclick: () => loadCity(city.id) }, city.name),
    ),
  );
}

function bindViewButtons() {
  for (const button of document.querySelectorAll(".views button")) {
    button.addEventListener("click", () => setView(button.dataset.view));
  }
}

function setView(view, { force = false } = {}) {
  if (!force && view === state.view) return;
  state.view = view;
  for (const button of document.querySelectorAll(".views button")) {
    button.setAttribute("aria-pressed", String(button.dataset.view === view));
  }
  for (const name of ["map", "graph", "compare"]) {
    document.getElementById("view-" + name).hidden = name !== view;
  }
  if (state.twin) syncUrl();
  if (view === "map") renderMap();
  if (view === "graph") renderGraph();
  if (view === "compare") renderCompare();
}

/* Rail ------------------------------------------------------------- */

function renderLayers() {
  const list = document.getElementById("layers");
  const items = state.twin.layers.map((layer) => {
    const q = QUANTITY[layer.quantity_id] || { label: layer.quantity_id };
    const source = sourceOf(layer.source_id);
    const withData = state.twin.entities.filter((e) => e.capability_id === layer.capability_id && e.latest).length;
    let meta = layer.discovery_status === "unavailable"
      ? "Suche nach Messstellen fehlgeschlagen"
      : layer.entity_count === 0
        ? "Keine Messstellen im Suchgebiet gefunden"
        : `${layer.entity_count} Messstellen gefunden, ${withData} mit Werten`;
    if (layer.carried_over) {
      meta += `. ${layer.carried_over} Werte stammen vom Stand ${dateTime(layer.carried_over_from)}, weil die Quelle diesmal nichts geliefert hat`;
    }
    const problem = layer.availability !== "available";
    return h(
      "li",
      { class: "layer" },
      h(
        "label",
        {},
        h("input", { type: "checkbox", checked: !state.hidden.has(layer.capability_id), onchange: (e) => toggleLayer(layer.capability_id, e.target.checked) }),
        h("span", { class: "layer-name" }, h("span", { class: "swatch " + (layer.capability_id === "river_level" ? "gauge" : "temp") }), q.label),
        h("span", { class: "layer-meta" }, `${source ? source.provider : layer.source_id}`),
        h("span", { class: "layer-meta" + (problem ? " problem" : "") }, meta + (problem && layer.error ? `. Hinweis der Quelle: ${layer.error}` : "")),
      ),
    );
  });
  items.push(
    h(
      "li",
      { class: "layer" },
      h(
        "label",
        {},
        h("input", { type: "checkbox", checked: !state.hidden.has("relations"), onchange: (e) => toggleLayer("relations", e.target.checked) }),
        h("span", { class: "layer-name" }, h("span", { class: "swatch rel" }), "Beziehungen"),
        h("span", { class: "layer-meta" }, "Pegel zur nächsten Wetterstation, abgeleitet"),
      ),
    ),
  );
  list.replaceChildren(...items);
}

function toggleLayer(id, visible) {
  if (visible) state.hidden.delete(id);
  else state.hidden.add(id);
  if (state.view === "map") renderMap();
}

function entityButton(id) {
  const entity = entityById(id);
  const label = entity ? entity.label : id.split(":").pop();
  return h("button", { type: "button", class: "entity-link", onclick: () => select(id, { pan: true }) }, label);
}

function howBlock(run, rows) {
  const r = run.run;
  return h(
    "details",
    { class: "how" },
    h("summary", {}, "Wie berechnet?"),
    h(
      "dl",
      {},
      rows.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]),
      h("dt", {}, "Agent"),
      h("dd", {}, `${run.component_id}, Version ${run.version}`),
      h("dt", {}, "Eingaben"),
      h("dd", {}, run.inputs.map((c) => CAPABILITY[c] || c).join(", ")),
      r ? [h("dt", {}, "Berechnet"), h("dd", {}, dateTime(r.provenance.executed_at))] : null,
    ),
  );
}

function problemText(run) {
  if (!run.resolved) {
    const missing = run.unresolved.map((u) => CAPABILITY[u.capability_id] || u.capability_id).join(", ");
    return `Für ${state.twin.city.name} nicht verfügbar: Die Stadt bietet ${missing} nicht an.`;
  }
  if (!run.run) return "Nicht ausgeführt: In diesem Lauf kamen keine Messdaten für diese Auswertung an.";
  return run.run.problems.map((p) => PROBLEM[p.code] || p.message).join(" ");
}

function renderInsights() {
  const host = document.getElementById("insights");
  const blocks = [];

  const spreadRun = agent("temperature_spread");
  if (spreadRun) {
    const out = payload(spreadRun);
    if (out) {
      blocks.push(
        h(
          "article",
          { class: "insight" },
          h("h3", {}, "Temperaturunterschied in der Stadt"),
          h(
            "p",
            {},
            `Um ${clock(out.observed_at)} Uhr liegen zwischen ${out.station_count} Stationen ${num(out.spread, 1)} Grad. Am kühlsten ist es an `,
            entityButton(out.min.entity),
            ` (${num(out.min.value, 1)} °C), am wärmsten an `,
            entityButton(out.max.entity),
            ` (${num(out.max.value, 1)} °C).`,
          ),
          out.not_aligned.length ? h("p", { class: "hint" }, `${out.not_aligned.length} Station(en) ohne Wert zu diesem Zeitpunkt bleiben außen vor.`) : null,
          spreadRun.run.problems.length ? h("p", { class: "hint" }, problemText(spreadRun)) : null,
          howBlock(spreadRun, [
            ["Regel", "Nur Stationen mit demselben Messzeitpunkt, mindestens drei. Nichts wird interpoliert."],
            ["Mittelwert", `${num(out.mean, 2)} °C`],
            ["Grenze", "Unterschiede spiegeln auch Höhe und Umgebung der Stationen. Das ist allein kein Nachweis einer Wärmeinsel."],
          ]),
        ),
      );
    } else {
      blocks.push(h("article", { class: "insight unanswered" }, h("h3", {}, "Temperaturunterschied in der Stadt"), h("p", {}, problemText(spreadRun)), howBlock(spreadRun, [["Regel", "Nur Stationen mit demselben Messzeitpunkt, mindestens drei."]])));
    }
  }

  const trendRun = agent("water_level_trend");
  if (trendRun) {
    const out = payload(trendRun);
    if (out) {
      const order = { rising: 0, falling: 1, steady: 2, unknown: 3 };
      const gauges = [...out.gauges].sort((a, b) => order[a.trend] - order[b.trend] || Math.abs(Number(b.change || 0)) - Math.abs(Number(a.change || 0)));
      const moving = gauges.filter((g) => g.trend === "rising" || g.trend === "falling").length;
      blocks.push(
        h(
          "article",
          { class: "insight" },
          h("h3", {}, "Pegel in den letzten sechs Stunden"),
          h("p", {}, moving ? `${moving} von ${gauges.length} Pegeln bewegen sich deutlich.` : `Alle ${gauges.length} Pegel sind weitgehend gleichbleibend.`),
          h("ul", {}, gauges.filter((g) => g.trend !== "steady").map(trendItem)),
          gauges.some((g) => g.trend === "steady")
            ? h(
                "details",
                { class: "more" },
                h("summary", {}, `${gauges.filter((g) => g.trend === "steady").length} gleichbleibende Pegel`),
                h("ul", {}, gauges.filter((g) => g.trend === "steady").map(trendItem)),
              )
            : null,
          trendRun.run.problems.length ? h("p", { class: "hint" }, problemText(trendRun)) : null,
          howBlock(trendRun, [["Regel", `Letzter Wert minus Messwert von vor ${out.window_hours} Stunden (±${out.tolerance_minutes} Minuten). Ab ${out.threshold_cm} cm steigend oder fallend.`]]),
        ),
      );
    } else {
      blocks.push(h("article", { class: "insight unanswered" }, h("h3", {}, "Pegel in den letzten sechs Stunden"), h("p", {}, problemText(trendRun))));
    }
  }
  host.replaceChildren(...blocks);
}

function trendItem(g) {
  return h(
    "li",
    {},
    h("span", { class: "trend-" + g.trend, "aria-hidden": "true" }, TREND_ARROW[g.trend] + " "),
    entityButton(g.entity),
    g.change === null ? `: ${TREND[g.trend]}` : `: ${signed(g.change)} cm, ${TREND[g.trend]}`,
  );
}

function renderCredits() {
  const credits = document.getElementById("credits");
  const sources = state.twin.city.sources.filter((s) => state.twin.layers.some((l) => l.source_id === s.id));
  credits.replaceChildren(
    ...sources.map((s) =>
      h("p", {}, `${s.provider}`, s.license.identifier ? `, Lizenz ${s.license.identifier}` : "", s.license.terms_url ? [" (", h("a", { href: s.license.terms_url, rel: "noopener" }, "Bedingungen"), ")"] : ""),
    ),
    h("p", {}, "Kartengrundlage © OpenStreetMap-Mitwirkende, © CARTO."),
    h("p", {}, h("a", { href: "https://github.com/nfloser/urbanium" }, "Quellcode auf GitHub"), ", ", h("a", { href: "catalog/" }, "Quellenkatalog")),
  );
}

/* Map -------------------------------------------------------------- */

function ensureMap() {
  if (state.map) return state.map;
  state.map = L.map("map", { zoomControl: true, attributionControl: true, zoomSnap: 0.25 });
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    subdomains: "abcd",
    maxZoom: 18,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende, © <a href="https://carto.com/attributions">CARTO</a>',
  }).addTo(state.map);
  state.map.attributionControl.setPrefix(false);
  state.overlays = L.layerGroup().addTo(state.map);
  state.map.on("zoomend", () => setTimeout(declutter, 0));
  // Keyboard selection is handled here rather than relying on Leaflet's
  // keypress-to-click translation, which does not fire for these markers.
  document.getElementById("map").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const host = event.target.closest && event.target.closest(".mk-host");
    const label = host && (host.querySelector(".part.current + .sep + [data-entity]") || host.querySelector("[data-entity]"));
    if (!label) return;
    event.preventDefault();
    select(label.dataset.entity, { toggle: false });
  });
  const legend = document.getElementById("legend");
  legend.replaceChildren(
    h("div", { class: "scale" }, "−10°", h("span", { class: "ramp", style: `background: linear-gradient(90deg, ${[-10, 0, 10, 20, 30].map(tempColor).join(",")})` }), "30°"),
    h("div", {}, "Gestrichelt: veraltet oder zuletzt bekannt. Leer: keine Werte."),
  );
  return state.map;
}

function renderMap() {
  const map = ensureMap();
  const twin = state.twin;
  const cityChanged = map._urbaniumCity !== twin.city.id;
  map._urbaniumCity = twin.city.id;
  state.overlays.clearLayers();
  state.markers.clear();

  const area = twin.city.area;
  if (area) {
    L.rectangle([[area.south, area.west], [area.north, area.east]], { color: "#15263a", weight: 1, dashArray: "2 6", fill: false, interactive: false }).addTo(state.overlays);
  }

  if (!state.hidden.has("relations")) {
    for (const rel of twin.relations) {
      if (rel.assertion.predicate !== "nearest_weather_station") continue;
      const a = entityById(canonical(rel.assertion.subject));
      const b = entityById(canonical(rel.assertion.object));
      if (!a || !b) continue;
      if (state.hidden.has(a.capability_id) || state.hidden.has(b.capability_id)) continue;
      L.polyline([[a.latitude, a.longitude], [b.latitude, b.longitude]], { color: "#b7791f", weight: 1.5, dashArray: "5 5", interactive: false }).addTo(state.overlays);
    }
  }

  for (const group of siteGroups(twin.entities.filter((e) => !state.hidden.has(e.capability_id)))) {
    const lead = group[0];
    const lat = group.reduce((sum, e) => sum + e.latitude, 0) / group.length;
    const lon = group.reduce((sum, e) => sum + e.longitude, 0) / group.length;
    const marker = L.marker([lat, lon], {
      icon: markerIcon(group),
      keyboard: true,
      title: group.map((e) => `${e.label}: ${valueText(e)}`).join(", "),
      riseOnHover: true,
    });
    marker.bindTooltip(() => h("div", {}, group.map(tooltip)), { className: "tip", direction: "top", offset: [6, -10], opacity: 1 });
    marker.on("click", (event) => {
      const part = event.originalEvent && event.originalEvent.target.closest && event.originalEvent.target.closest("[data-entity]");
      select(part ? part.dataset.entity : lead.id, { toggle: false });
    });
    marker.addTo(state.overlays);
    for (const e of group) state.markers.set(e.id, marker);
    marker._urbaniumGroup = group;
  }

  if (cityChanged) {
    map.invalidateSize();
    // Frame what was found, not the whole search envelope; fall back to the area.
    const points = twin.entities.map((e) => [e.latitude, e.longitude]);
    const bounds = points.length > 1 ? L.latLngBounds(points) : area ? L.latLngBounds([[area.south, area.west], [area.north, area.east]]) : null;
    if (bounds) map.fitBounds(bounds, { paddingTopLeft: [90, 30], paddingBottomRight: [70, 30], maxZoom: 13, animate: false });
    else if (points.length === 1) map.setView(points[0], 12, { animate: false });
  }
  setTimeout(() => {
    map.invalidateSize();
    declutter();
  }, 0);
}

/* Entities closer than this share one label, e.g. the upper and lower gauge of a lock. */
const SITE_METRES = 400;

function metres(a, b) {
  const rad = Math.PI / 180;
  const x = (b.longitude - a.longitude) * rad * Math.cos(((a.latitude + b.latitude) / 2) * rad);
  const y = (b.latitude - a.latitude) * rad;
  return Math.hypot(x, y) * 6371000;
}

function siteGroups(entities) {
  const groups = [];
  for (const entity of entities) {
    const group = groups.find((g) => g[0].entity_type === entity.entity_type && g.every((other) => metres(other, entity) < SITE_METRES));
    if (group) group.push(entity);
    else groups.push([entity]);
  }
  return groups.map((g) => g.sort((a, b) => a.label.localeCompare(b.label, "de")));
}

/* Short distinguishing part of names in one group: "BERLIN-SPANDAU OP" and "… UP" give "OP", "UP". */
function partNames(group) {
  const words = group.map((e) => e.label.split(/\s+/));
  let common = 0;
  while (words.every((w) => w.length > common + 1 && w[common] === words[0][common])) common++;
  const parts = words.map((w) => w.slice(common).join(" "));
  return parts.every((p) => p && p.length <= 12) && new Set(parts).size === parts.length ? parts : group.map((_, i) => String(i + 1));
}

/* Hide the text of labels that would overlap a more important one; symbols always stay. */
function declutter() {
  if (!state.map) return;
  const seen = new Set();
  const items = [];
  for (const marker of state.markers.values()) {
    if (seen.has(marker)) continue;
    seen.add(marker);
    const el = marker.getElement();
    const label = el && el.querySelector(".mk");
    if (!label) continue;
    label.classList.remove("muted");
    const group = marker._urbaniumGroup || [];
    const selected = group.some((e) => e.id === state.selected);
    const trend = group.map((e) => trendFor(e.id)).find((t) => t && (t.trend === "rising" || t.trend === "falling"));
    const rank = selected ? 0 : group[0] && group[0].entity_type === "weather_station" ? 1 : trend ? 2 : 3;
    const sym = label.querySelector(".sym");
    items.push({ label, rank, rect: label.getBoundingClientRect(), sym: sym ? sym.getBoundingClientRect() : null });
  }
  items.sort((a, b) => a.rank - b.rank || a.rect.top - b.rect.top || a.rect.left - b.rect.left);
  const overlaps = (r, p) => r.left < p.right + 2 && r.right > p.left - 2 && r.top < p.bottom + 1 && r.bottom > p.top - 1;
  // Symbols always stay visible, so every other marker's symbol is an obstacle.
  const symbols = items.filter((item) => item.sym);
  const placed = [];
  for (const item of items) {
    const r = item.rect;
    // The selected label always stays readable; everything else yields to it.
    const hit = item.rank > 0 && (placed.some((p) => overlaps(r, p)) || symbols.some((other) => other !== item && overlaps(r, other.sym)));
    if (hit) item.label.classList.add("muted");
    else placed.push(r);
  }
}

function canonical(ref) {
  return `${ref.city_id}:${ref.entity_type}:${ref.entity_id}`;
}

function markerIcon(group) {
  const entity = group[0];
  const classes = ["mk", entity.entity_type === "river_gauge" ? "mk-gauge" : "mk-temp"];
  if (group.every((e) => e.freshness === "stale")) classes.push("stale");
  if (group.every((e) => e.freshness === "last_known")) classes.push("lastknown");
  if (group.every((e) => e.freshness === "no_data")) classes.push("nodata");
  if (group.some((e) => e.id === state.selected)) classes.push("selected");
  let style = "";
  if (entity.entity_type === "weather_station" && entity.latest) style = ` style="--c:${tempColor(entity.latest.value)}"`;
  const names = partNames(group);
  const parts = group.map((e, i) => {
    let arrow = "";
    const trend = e.entity_type === "river_gauge" ? trendFor(e.id) : null;
    if (trend && (trend.trend === "rising" || trend.trend === "falling")) arrow = ` <span class="arrow trend-${trend.trend}" aria-hidden="true">${TREND_ARROW[trend.trend]}</span>`;
    const prefix = group.length > 1 ? `<span class="part-name">${esc(names[i])}</span> ` : "";
    const value = group.length > 1 ? valueText(e, false) : valueText(e);
    return `<span class="part${e.id === state.selected ? " current" : ""}" data-entity="${esc(e.id)}">${prefix}${esc(value)}${arrow}</span>`;
  });
  const unit = group.length > 1 && entity.latest ? `<span class="part-unit">${esc(QUANTITY[entity.latest.quantity_id] ? QUANTITY[entity.latest.quantity_id].unit : entity.latest.unit)}</span>` : "";
  return L.divIcon({
    className: "mk-host",
    html: `<span class="${classes.join(" ")}"${style}>${entity.entity_type === "river_gauge" ? "" : '<i class="sym"></i>'}${parts.join('<span class="sep" aria-hidden="true">/</span>')}${unit}${entity.entity_type === "river_gauge" ? '<i class="sym"></i>' : ""}</span>`,
    iconSize: [0, 0],
    iconAnchor: [0, 0],
  });
}

function tooltip(entity) {
  const q = entity.latest ? QUANTITY[entity.latest.quantity_id] : null;
  return h(
    "div",
    {},
    h("strong", {}, entity.label),
    h("span", { class: "v" }, entity.latest ? `${valueText(entity, false)} ${q ? q.unit : entity.latest.unit}` : "Keine Werte"),
    entity.latest ? h("div", { class: "t" }, `${q ? q.label : ""}, gemessen ${dateTime(entity.latest.observed_at)}, ${FRESHNESS[entity.freshness]}`) : h("div", { class: "t" }, "Im Inventar gelistet, aber ohne aktuelle Messung"),
    entity.carried_over_from ? h("div", { class: "t" }, `Vom Stand ${dateTime(entity.carried_over_from)} übernommen; die Quelle hat diesmal nichts geliefert`) : null,
    h("div", { class: "t" }, (sourceOf(entity.source_id) || {}).provider || entity.source_id),
  );
}

/* Selection and detail -------------------------------------------- */

function select(id, { pan = false, toggle = true } = {}) {
  const previous = state.selected;
  state.selected = toggle && state.selected === id && !pan ? null : id;
  if (previous === state.selected && !pan) return;
  renderDetail();
  if (state.view === "map") {
    const hadFocus = document.activeElement && document.activeElement.classList.contains("mk-host");
    for (const changed of new Set([previous, id])) {
      const marker = changed && state.markers.get(changed);
      if (marker && marker._urbaniumGroup) {
        marker.setIcon(markerIcon(marker._urbaniumGroup));
        marker.setZIndexOffset(marker._urbaniumGroup.some((e) => e.id === state.selected) ? 1000 : 0);
      }
    }
    declutter();
    const entity = entityById(id);
    const marker = state.markers.get(id);
    if (hadFocus && marker && marker.getElement()) marker.getElement().focus();
    if (pan && entity && state.map) state.map.panTo([entity.latitude, entity.longitude], { animate: !matchMedia("(prefers-reduced-motion: reduce)").matches });
  }
  if (state.view === "graph") renderGraph();
  if (state.view === "compare") setView("map");
}

function renderDetail() {
  const host = document.getElementById("detail");
  const entity = state.selected ? entityById(state.selected) : null;
  if (!entity) {
    host.replaceChildren(emptyDetail());
    return;
  }
  const q = entity.latest ? QUANTITY[entity.latest.quantity_id] : null;
  const source = sourceOf(entity.source_id);
  // Optional sections return null; replaceChildren would render those as text.
  host.replaceChildren(...[
    h(
      "div",
      { class: "detail-head" },
      h("div", {}, h("p", { class: "kind" }, ENTITY_KIND[entity.entity_type] || entity.entity_type), h("h2", {}, entity.label)),
      h("button", { type: "button", class: "close", onclick: () => select(entity.id), "aria-label": "Auswahl aufheben" }, "Schließen"),
    ),
    entity.latest
      ? h("div", {}, h("div", { class: "reading" }, h("span", { class: "big" }, valueText(entity, false)), h("span", { class: "unit" }, q ? q.unit : entity.latest.unit)), h("p", { class: "when" }, `${q ? q.label : ""}, gemessen ${dateTime(entity.latest.observed_at)}`, h("span", { class: `fresh fresh-${entity.freshness}` }, FRESHNESS[entity.freshness])))
      : h("p", { class: "when" }, "Diese Messstelle steht im Inventar der Quelle, hat in diesem Lauf aber keine Werte geliefert.", h("span", { class: "fresh fresh-no_data" }, FRESHNESS.no_data)),
    entity.carried_over_from
      ? h("p", { class: "carried" }, `Dieser Wert stammt aus dem Stand vom ${dateTime(entity.carried_over_from)}. Im aktuellen Lauf hat die Quelle nichts geliefert, deshalb fließt er in keine Auswertung ein.`)
      : null,
    entity.series.length > 1 ? sparkline(entity) : null,
    derivedNotes(entity),
    relationList(entity),
    h(
      "section",
      {},
      h("h3", {}, "Merkmale"),
      h(
        "dl",
        { class: "facts" },
        Object.entries(entity.attributes).flatMap(([k, v]) => [h("dt", {}, ATTRIBUTE[k] || k), h("dd", {}, attributeText(k, v))]),
        h("dt", {}, "Lage"),
        h("dd", {}, `${num(entity.latitude, 4)} N, ${num(entity.longitude, 4)} O`),
      ),
    ),
    h(
      "section",
      {},
      h("h3", {}, "Herkunft"),
      h(
        "dl",
        { class: "facts" },
        h("dt", {}, "Quelle"),
        h("dd", {}, source ? source.provider : entity.source_id),
        source && source.license ? [h("dt", {}, "Lizenz"), h("dd", {}, source.license.identifier || "siehe Bedingungen", source.license.terms_url ? [" (", h("a", { href: source.license.terms_url, rel: "noopener" }, "Bedingungen"), ")"] : "")] : null,
        entity.evidence.flatMap((ev) => [h("dt", {}, "Datensatz"), h("dd", {}, shortRecord(ev.record_id)), h("dt", {}, "Abgerufen"), h("dd", {}, dateTime(ev.retrieved_at))]),
        h("dt", {}, "Kennung"),
        h("dd", {}, entity.id),
      ),
    ),
  ].filter(Boolean));
}

function attributeText(key, value) {
  if (key === "elevation_m") return `${num(value)} m`;
  if (key === "gauge_zero_m") return `${num(value, 2)} m über NHN`;
  if (key === "river_km") return `km ${num(value, 1)}`;
  if (key === "inventory_until") return new Date(value).toLocaleDateString("de-DE");
  return String(value);
}

function shortRecord(record) {
  const parts = record.split(":");
  const hash = parts.pop();
  return /^[0-9a-f]{64}$/.test(hash) ? `${parts.join(":")}, Prüfsumme ${hash.slice(0, 12)}…` : record;
}

function emptyDetail() {
  const twin = state.twin;
  const withData = twin.entities.filter((e) => e.latest).length;
  const answered = twin.agents.filter((a) => a.run && a.run.status !== "unavailable").length;
  return h(
    "div",
    { class: "empty-detail" },
    h("h2", {}, twin.city.name),
    h("p", {}, "Wähle eine Messstelle auf der Karte oder im Graphen. Dann siehst du Wert, Verlauf, Beziehungen und woher jede Angabe stammt."),
    h(
      "dl",
      {},
      h("dt", {}, h("span", { class: "count" }, twin.entities.length)),
      h("dd", {}, `Messstellen automatisch im Suchgebiet gefunden, ${withData} davon mit Werten`),
      h("dt", {}, h("span", { class: "count" }, twin.relations.length)),
      h("dd", {}, "Aussagen im Wissensgraphen, jede mit Herkunft"),
      h("dt", {}, h("span", { class: "count" }, `${answered}/${twin.agents.length}`)),
      h("dd", {}, "Auswertungen beantwortbar"),
    ),
  );
}

function derivedNotes(entity) {
  const notes = [];
  if (entity.entity_type === "river_gauge") {
    const trend = trendFor(entity.id);
    if (trend) {
      notes.push(
        trend.change === null
          ? "Trend unbekannt: Es gibt keinen Messwert von vor etwa sechs Stunden."
          : `In sechs Stunden ${signed(trend.change)} cm (${TREND[trend.trend]}), verglichen mit ${num(trend.reference_value)} cm um ${clock(trend.reference_at)} Uhr.`,
      );
    }
  }
  if (entity.entity_type === "weather_station") {
    const out = payload(agent("temperature_spread"));
    if (out) {
      if (out.min.entity === entity.id) notes.push(`Kühlste von ${out.station_count} Stationen um ${clock(out.observed_at)} Uhr.`);
      else if (out.max.entity === entity.id) notes.push(`Wärmste von ${out.station_count} Stationen um ${clock(out.observed_at)} Uhr.`);
      else {
        const own = out.values.find((v) => v.entity === entity.id);
        if (own) notes.push(`${signed((Number(own.value) - Number(out.mean)).toFixed(1))} Grad gegenüber dem Mittel aller ${out.station_count} Stationen um ${clock(out.observed_at)} Uhr.`);
        else if (out.not_aligned.includes(entity.id)) notes.push(`Kein Wert um ${clock(out.observed_at)} Uhr, deshalb nicht im Stadtvergleich.`);
      }
    }
  }
  if (!notes.length) return null;
  return h("section", {}, h("h3", {}, "Einordnung"), ...notes.map((n) => h("p", { class: "derived-note" }, n)));
}

function relationList(entity) {
  const items = [];
  for (const rel of state.twin.relations) {
    const a = rel.assertion;
    const subject = canonical(a.subject);
    const object = canonical(a.object);
    const derived = a.state_category === "derived";
    if (subject === entity.id) {
      const target = entityById(object);
      items.push(
        h(
          "li",
          { class: derived ? "derived" : "" },
          h("span", { class: "pred" }, PREDICATE[a.predicate] || a.predicate, derived ? ", abgeleitet" : ", laut Quelle"),
          target ? entityButton(object) : rel.object_label || a.object.entity_id,
          rel.distance_km !== null ? ` in ${num(rel.distance_km, 1)} km` : "",
        ),
      );
    } else if (object === entity.id && a.predicate !== "located_in") {
      items.push(
        h(
          "li",
          { class: derived ? "derived" : "" },
          h("span", { class: "pred" }, INVERSE[a.predicate] || a.predicate, derived ? ", abgeleitet" : ", laut Quelle"),
          entityButton(subject),
          rel.distance_km !== null ? ` in ${num(rel.distance_km, 1)} km` : "",
        ),
      );
    }
  }
  if (!items.length) return null;
  return h("section", {}, h("h3", {}, "Beziehungen"), h("ul", { class: "relations" }, items));
}

function sparkline(entity) {
  const points = entity.series.map(([t, v]) => [new Date(t).getTime(), Number(v)]);
  const W = 300, H = 88, P = { l: 2, r: 2, t: 16, b: 16 };
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const X = (x) => P.l + ((x - x0) / (x1 - x0 || 1)) * (W - P.l - P.r);
  const Y = (y) => P.t + (1 - (y - y0) / (y1 - y0)) * (H - P.t - P.b);
  const line = points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
  const area = `${line}L${X(x1).toFixed(1)},${H - P.b}L${X(x0).toFixed(1)},${H - P.b}Z`;
  const unit = entity.latest && QUANTITY[entity.latest.quantity_id] ? QUANTITY[entity.latest.quantity_id].short.trim() : "";
  const digits = entity.latest && entity.latest.quantity_id === "air_temperature" ? 1 : 0;
  return h(
    "section",
    {},
    h("h3", {}, "Verlauf"),
    svg(
      "svg",
      { class: "spark", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": `Verlauf von ${num(Math.min(...ys), digits)} bis ${num(Math.max(...ys), digits)} ${unit} zwischen ${clock(entity.series[0][0])} und ${clock(entity.series[entity.series.length - 1][0])} Uhr` },
      svg("path", { class: "area", d: area }),
      svg("path", { class: "line", d: line, "vector-effect": "non-scaling-stroke" }),
      svg("text", { x: 2, y: 11 }, `höchster Wert ${num(Math.max(...ys), digits)} ${unit}, niedrigster ${num(Math.min(...ys), digits)} ${unit}`),
      svg("text", { x: 2, y: H - 3 }, dateTime(entity.series[0][0])),
      svg("text", { x: W - 2, y: H - 3, "text-anchor": "end" }, dateTime(entity.series[entity.series.length - 1][0])),
    ),
  );
}

/* Knowledge graph -------------------------------------------------- */

function renderGraph() {
  const host = document.getElementById("graph");
  const twin = state.twin;
  const box = host.getBoundingClientRect();
  const W = Math.max(box.width, 640), Hgt = Math.max(box.height, 420);
  host.setAttribute("viewBox", `0 0 ${W} ${Hgt}`);

  const nodes = new Map();
  const add = (id, kind, label, sub) => { if (!nodes.has(id)) nodes.set(id, { id, kind, label, sub }); };
  for (const e of twin.entities) add(e.id, e.entity_type, e.label, valueText(e));
  for (const rel of twin.relations) {
    const o = rel.assertion.object;
    add(canonical(o), o.entity_type, rel.object_label || o.entity_id, ENTITY_KIND[o.entity_type]);
  }
  const columns = [["weather_station", "Wetterstationen"], ["river_gauge", "Pegel"], ["water_body", "Gewässer"]];
  const area = [...nodes.values()].find((n) => n.kind === "discovery_area");
  const layout = new Map();
  const colX = (c) => W * [0.06, 0.38, 0.7][c];
  // Order columns to reduce crossings: gauges grouped by water body, water bodies
  // by their first gauge, stations by the mean position of the gauges they serve.
  const linked = (predicate) => twin.relations.filter((r) => r.assertion.predicate === predicate).map((r) => [canonical(r.assertion.subject), canonical(r.assertion.object)]);
  const waterOf = new Map(linked("on_water_body"));
  const gaugeOrder = [...nodes.values()].filter((n) => n.kind === "river_gauge")
    .sort((a, b) => String(waterOf.get(a.id)).localeCompare(String(waterOf.get(b.id))) || a.label.localeCompare(b.label, "de"))
    .map((n) => n.id);
  const nearest = linked("nearest_weather_station");
  const rank = (node) => {
    if (node.kind === "river_gauge") return gaugeOrder.indexOf(node.id);
    const peers = node.kind === "water_body"
      ? [...waterOf].filter(([, w]) => w === node.id).map(([g]) => gaugeOrder.indexOf(g))
      : nearest.filter(([, st]) => st === node.id).map(([g]) => gaugeOrder.indexOf(g));
    if (!peers.length) return 1e6;
    return node.kind === "water_body" ? Math.min(...peers) : peers.reduce((a, b) => a + b, 0) / peers.length;
  };
  columns.forEach(([kind], c) => {
    const items = [...nodes.values()].filter((n) => n.kind === kind).sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label, "de"));
    const x = colX(c);
    const top = 70, bottom = Hgt - 90;
    items.forEach((n, i) => layout.set(n.id, { x, y: items.length === 1 ? (top + bottom) / 2 : top + (i * (bottom - top)) / (items.length - 1) }));
  });
  if (area) layout.set(area.id, { x: W / 2, y: Hgt - 34 });

  const edges = twin.relations.map((rel) => ({
    a: canonical(rel.assertion.subject),
    b: canonical(rel.assertion.object),
    predicate: rel.assertion.predicate,
    kind: rel.assertion.predicate === "located_in" ? "faint" : rel.assertion.state_category === "derived" ? "derived" : "reference",
  }));
  const sel = state.selected;
  const edgeEls = edges
    .filter((e) => layout.has(e.a) && layout.has(e.b))
    .sort((x, y) => (x.kind === "faint") - (y.kind === "faint")).reverse()
    .map((e) => {
      const p = layout.get(e.a), q = layout.get(e.b);
      const mx = (p.x + q.x) / 2;
      const d = e.kind === "faint" ? `M${p.x},${p.y}L${q.x},${q.y}` : `M${p.x},${p.y}C${mx},${p.y} ${mx},${q.y} ${q.x},${q.y}`;
      const hot = sel && (e.a === sel || e.b === sel) && e.kind !== "faint";
      return svg("path", { class: `edge ${e.kind}${hot ? " hot" : ""}`, d }, svg("title", {}, PREDICATE[e.predicate] || e.predicate));
    });

  const nodeEls = [...nodes.values()].filter((n) => layout.has(n.id)).map((n) => {
    const { x, y } = layout.get(n.id);
    const entity = entityById(n.id);
    const fill = n.kind === "weather_station" ? (entity && entity.latest ? tempColor(entity.latest.value) : "#fff") : n.kind === "river_gauge" ? "#1f6fb2" : n.kind === "water_body" ? "#cfe0ef" : "#e8edee";
    const shape = n.kind === "river_gauge" ? svg("rect", { x: -7, y: -7, width: 14, height: 14, transform: "rotate(45)", fill }) : svg("circle", { r: n.kind === "discovery_area" ? 10 : 8, fill });
    const right = true;
    const clickable = Boolean(entity);
    return svg(
      "g",
      {
        class: "node" + (sel === n.id ? " selected" : ""),
        transform: `translate(${x},${y})`,
        tabindex: clickable ? 0 : null,
        role: clickable ? "button" : null,
        "aria-label": `${ENTITY_KIND[n.kind] || n.kind} ${n.label}`,
        onclick: clickable ? () => select(n.id) : null,
        onkeydown: clickable ? (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(n.id); } } : null,
      },
      shape,
      svg("title", {}, n.label),
      svg("text", { x: right ? 14 : -14, y: -1, "text-anchor": right ? "start" : "end" }, n.label.length > 26 ? n.label.slice(0, 25) + "…" : n.label),
      n.sub ? svg("text", { class: "sub", x: right ? 14 : -14, y: 14, "text-anchor": right ? "start" : "end" }, n.kind === "discovery_area" ? "alle Messstellen liegen darin" : n.sub) : null,
    );
  });
  const heads = columns.map(([, title], c) => svg("text", { class: "column", x: colX(c) - 8, y: 36 }, title));
  host.replaceChildren(...heads, ...edgeEls, ...nodeEls);
}

/* Compare ---------------------------------------------------------- */

function renderCompare() {
  const host = document.getElementById("view-compare");
  const cities = state.index.cities;
  const capabilities = ["weather", "river_level", "realtime_transport", "open_data_catalog"];
  const caps = new Map();
  Promise.all(cities.map((c) => (c.id === state.twin.city.id ? Promise.resolve(state.twin) : fetchJson(DATA + c.id + ".json").catch(() => null)))).then((twins) => {
    twins.forEach((t, i) => caps.set(cities[i].id, t));
    const row = (cap) =>
      h(
        "tr",
        {},
        h("th", { scope: "row" }, CAPABILITY[cap]),
        cities.map((c) => {
          const twin = caps.get(c.id);
          const declared = twin ? twin.city.capabilities.find((x) => x.id === cap) : null;
          const layer = c.layers.find((l) => l.capability_id === cap);
          if (!declared) return h("td", {}, h("span", { class: "cell-main off" }, "nicht angegeben"));
          const sources = twin.city.sources.filter((src) => src.capabilities.includes(cap));
          return h(
            "td",
            {},
            h("span", { class: "cell-main" + (declared.support === "configured" ? "" : " off") }, SUPPORT[declared.support] || declared.support),
            layer ? h("span", { class: "cell-sub" }, `${layer.entity_count} Messstellen, ${AVAILABILITY[layer.availability]}`) : declared.support === "configured" ? h("span", { class: "cell-sub" }, "nicht im Twin-Snapshot") : null,
            sources.length || declared.notes
              ? h(
                  "details",
                  { class: "cell-more" },
                  h("summary", {}, "Quellen und Hinweise"),
                  sources.map((src) => h("span", { class: "cell-sub" }, `${src.provider} (${src.status === "verified" ? "geprüft" : "Kandidat"})`)),
                  declared.notes ? h("span", { class: "cell-sub" }, declared.notes) : null,
                )
              : null,
          );
        }),
      );
    host.replaceChildren(
      h("h2", {}, "Gleiche Plattform, unterschiedliche Städte"),
      h("p", {}, "Jede Stadt gibt an, welche Fähigkeiten sie hat. Was fehlt, bleibt sichtbar fehlend und wird nicht aufgefüllt. Auswertungen laufen nur dort, wo ihre Eingaben vorhanden sind."),
      h(
        "table",
        { class: "matrix" },
        h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Fähigkeit"), cities.map((c) => h("th", { scope: "col" }, h("button", { type: "button", onclick: () => loadCity(c.id).then(() => setView("map")) }, c.name))))),
        h(
          "tbody",
          {},
          capabilities.map(row),
          h("tr", {}, h("th", { scope: "row" }, "Beantwortbare Auswertungen"), cities.map((c) => h("td", {}, h("span", { class: "cell-main" }, `${c.agents_answered} von ${c.agents_total}`)))),
        ),
      ),
      h(
        "p",
        { class: "export-row" },
        h("button", { type: "button", class: "action", onclick: () => exportComparison(cities, caps, capabilities) }, "Vergleich als JSON speichern"),
        h("span", { class: "hint" }, " Enthält Fähigkeiten, Quellen, Hinweise und die Abdeckung dieses Stands."),
      ),
      h(
        "section",
        {},
        h("h2", {}, "Eine Stadt hinzufügen"),
        h("p", {}, "Hamburg und Köln kamen ohne eine Zeile Code dazu. Eine Stadt braucht ein Suchgebiet und die Quellen, die sie nutzt. Bundesweite Quellen finden ihre Messstellen darin selbst."),
        h("pre", { class: "yaml" }, yamlExample(caps.get("koeln") || state.twin)),
        h(
          "ol",
          { class: "steps" },
          h("li", {}, "Ordner cities/<stadt>/ mit dieser city.yaml anlegen."),
          h("li", {}, "In providers/ die Bindungen dwd_air_temperature_area.yaml und pegelonline.yaml ablegen."),
          h("li", {}, "urbanium-twin build ausführen. Die Stadt erscheint hier mit allem, was die Quellen in ihrem Gebiet hergeben."),
        ),
      ),
    );
  });
}

function comparisonDocument(cities, twins, capabilities) {
  return {
    schema_id: "urbanium.city-comparison/1",
    snapshot_generated_at: state.index.generated_at,
    data_mode: state.index.data_mode,
    note: "Registry support and snapshot coverage at the time of the snapshot; not a live health check.",
    cities: cities.map((c) => {
      const twin = twins.get(c.id);
      return {
        id: c.id,
        name: c.name,
        agents_answered: c.agents_answered,
        agents_total: c.agents_total,
        capabilities: capabilities.map((cap) => {
          const declared = twin ? twin.city.capabilities.find((x) => x.id === cap) : null;
          const layer = c.layers.find((l) => l.capability_id === cap) || null;
          return {
            id: cap,
            support: declared ? declared.support : "not_declared",
            notes: declared ? declared.notes || null : null,
            sources: twin ? twin.city.sources.filter((s) => s.capabilities.includes(cap)).map((s) => ({ id: s.id, provider: s.provider, status: s.status, licence: s.license.identifier || null })) : [],
            snapshot: layer ? { entity_count: layer.entity_count, availability: layer.availability, freshness: layer.freshness } : null,
          };
        }),
      };
    }),
  };
}

function exportComparison(cities, twins, capabilities) {
  const blob = new Blob([JSON.stringify(comparisonDocument(cities, twins, capabilities), null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = h("a", { href: url, download: `urbanium-staedtevergleich-${state.index.generated_at.slice(0, 10)}.json` });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function yamlExample(twin) {
  const c = twin.city;
  const lines = [
    `id: ${c.id}`,
    `name: ${c.name}`,
    `timezone: ${c.timezone}`,
    "area:",
    `  south: ${c.area.south}`,
    `  west: ${c.area.west}`,
    `  north: ${c.area.north}`,
    `  east: ${c.area.east}`,
    "capabilities:",
    ...c.capabilities.map((x) => `  - id: ${x.id}\n    support: ${x.support}`),
    "sources:",
    ...c.sources.map((s) => `  - id: ${s.id}\n    capabilities: [${s.capabilities.join(", ")}]`),
  ];
  return lines.join("\n");
}

window.addEventListener("resize", () => {
  if (state.view === "graph" && state.twin) renderGraph();
});

start();
