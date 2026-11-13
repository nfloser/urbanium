const labels = {
  weather: "Wetter",
  realtime_transport: "Nahverkehr in Echtzeit",
  river_level: "Pegelstand",
  open_data_catalog: "Open-Data-Katalog",
};
const supportLabels = {
  configured: "Konfiguriert",
  candidate: "Integration wird geprüft",
  unavailable: "Nicht verfügbar",
  unknown: "Noch ungeklärt",
};
const capability = document.querySelector("#capability");
const cityControls = document.querySelector("#cities");
const status = document.querySelector("#status");
const results = document.querySelector("#results");
const download = document.querySelector("#download");

function element(tag, text) {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
}

function compare(cities, cityIds, capabilityId) {
  return cities.filter((city) => cityIds.has(city.id)).map((city) => ({
    city_id: city.id,
    city_name: city.name,
    capability: city.capabilities.find((item) => item.id === capabilityId) ?? null,
    sources: city.sources.filter((source) => source.capabilities.includes(capabilityId)),
  }));
}

function card(row) {
  const article = document.createElement("article");
  const support = row.capability?.support;
  article.append(
    element("h3", row.city_name),
    element("strong", support ? supportLabels[support] ?? support : "Nicht im Katalog"),
  );
  if (row.capability?.notes) article.append(element("p", row.capability.notes));
  if (row.sources.length) {
    const list = document.createElement("ul");
    for (const source of row.sources) {
      const state = source.status === "verified" ? "verifiziert" : source.status;
      list.append(element("li", `${source.provider} · ${state}`));
    }
    article.append(element("h4", "Hinterlegte Quellen"), list);
  } else {
    article.append(element("p", "Für diese Funktion ist keine Quelle hinterlegt."));
  }
  return article;
}

async function start() {
  const response = await fetch("./catalog.json");
  if (!response.ok) throw new Error(`Catalog HTTP ${response.status}`);
  const cities = await response.json();
  const ids = new Set(cities.flatMap((city) => city.capabilities.map((item) => item.id)));
  for (const id of [...ids].sort()) capability.add(new Option(labels[id] ?? id, id));
  if (ids.has("realtime_transport")) capability.value = "realtime_transport";

  for (const city of cities) {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = city.id;
    checkbox.checked = true;
    label.append(checkbox, ` ${city.name}`);
    cityControls.append(label);
  }

  let rows;
  function update() {
    const selected = new Set(
      Array.from(cityControls.querySelectorAll("input:checked"), (input) => input.value),
    );
    rows = compare(cities, selected, capability.value);
    results.replaceChildren(...rows.map(card));
    status.textContent = rows.length
      ? `Katalogstand · ${rows.length} von ${cities.length} Städten ausgewählt`
      : "Wähle mindestens eine Stadt aus.";
    download.disabled = rows.length === 0;
  }

  download.addEventListener("click", () => {
    const payload = { mode: "catalog_snapshot", capability_id: capability.value, results: rows };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `urbanium-${capability.value}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  capability.addEventListener("change", update);
  cityControls.addEventListener("change", update);
  document.querySelector("#controls").disabled = false;
  update();
}

start().catch(() => {
  status.textContent = "Der Stadtkatalog konnte nicht geladen werden. Bitte lade die Seite neu.";
});
