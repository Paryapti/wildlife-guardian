
const $ = (id) => document.getElementById(id);

const COLORS = {
  EX: "--ex",
  EW: "--ew",
  CR: "--cr",
  EN: "--en",
  VU: "--vu",
  NT: "--nt",
  LC: "--lc",
  DD: "--dd"
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[c]));

const mode = () =>
  document.querySelector('input[name="mode"]:checked').value;

const statusVar = (code) =>
  `var(${COLORS[code] || "--dd"})`;

/* Make a safe image element as HTML.
   The URL is escaped, and failed images are hidden. */
function imageMarkup(url, name, className = "species-image") {
  if (!url) {
    return "";
  }

  return `
    <div class="species-image-wrap">
      <img
        class="${className}"
        src="${esc(url)}"
        alt="${esc(name || "Animal image")}"
        loading="lazy"
        referrerpolicy="no-referrer"
        onerror="this.closest('.species-image-wrap')?.remove()"
      >
    </div>
  `;
}

/* Image block for a related species, with a placeholder if unavailable. */
function relatedImageMarkup(species) {
  if (species.image_url) {
    return `
      <img
        class="related-image"
        src="${esc(species.image_url)}"
        alt="${esc(species.common_name || "Animal image")}"
        loading="lazy"
        referrerpolicy="no-referrer"
        onerror="this.outerHTML='<div class=&quot;related-placeholder&quot; aria-label=&quot;Image unavailable&quot;>🐾</div>'"
      >
    `;
  }

  return `<div class="related-placeholder" aria-label="Image unavailable">🐾</div>`;
}

async function search(name) {
  name = (name ?? $("q").value).trim();

  if (!name) {
    $("q").focus();
    return;
  }

  $("q").value = name;
  $("results").setAttribute("aria-busy", "true");
  $("results").innerHTML = `<p class="empty">Searching species and preparing results...</p>`;

  try {
    const response = await fetch(
      `/api/search?name=${encodeURIComponent(name)}&tree=${encodeURIComponent(mode())}`
    );

    const data = await response.json();

    if (!response.ok) {
      $("results").innerHTML =
        `<p class="error">${esc(data.error || "Unable to search for this species.")}</p>`;
      $("readout").hidden = true;
      return;
    }

    renderReadout(data);

    // In compare mode, show AVL results first and compare metrics for both.
    // Otherwise, show the selected tree's results.
    const selectedResult = data.avl || data.bst;

    renderResults(selectedResult, name);
  } catch (error) {
    console.error("Species search failed:", error);
    $("results").innerHTML = `
      <p class="error">
        Could not connect to the server. Please check that the Flask app is running and try again.
      </p>
    `;
    $("readout").hidden = true;
  } finally {
    $("results").setAttribute("aria-busy", "false");
  }
}

function renderReadout(data) {
  const kinds = Object.keys(data);

  const total = (metrics) =>
    metrics.name_comparisons + metrics.rank_comparisons;

  const max = Math.max(
    ...kinds.map((k) => total(data[k].metrics)),
    1
  );

  const rows = kinds.map((k) => {
    const m = data[k].metrics;
    const label = k === "avl" ? "AVL tree" : "Plain BST";
    const comparisons = total(m);
    const width = (comparisons / max) * 100;

    return `
      <div class="row">
        <span>${label}</span>
        <span class="bar" role="img"
          aria-label="${comparisons} comparisons">
          <i class="${k}" style="width:${width}%"></i>
        </span>
        <small>
          <b>${comparisons.toLocaleString()}</b> comparisons,
          ${esc(m.time_us)} µs
        </small>
      </div>
    `;
  }).join("");

  const facts = kinds.map((k) => {
    const m = data[k].metrics;
    const label = k === "avl" ? "AVL" : "BST";

    return `${label} name tree: ${m.tree_nodes.toLocaleString()} nodes, height ${m.name_tree_height}; ranking tree height ${m.rank_tree_height}.`;
  }).join(" ");

  $("readout").innerHTML = `
    <h2>How much work this search took</h2>
    ${rows}
    <p class="facts">${esc(facts)}</p>
  `;

  $("readout").hidden = false;
}

function chip(r) {
  return `
    <span class="chip" style="--s:${statusVar(r.status_code)}">
      ${esc(r.status || r.status_code || "Unknown status")}
    </span>
  `;
}

function renderResults(r, name) {
  if (!r || !r.found) {
    const suggestions = r?.suggestions || [];

    const hints = suggestions.map((s) => `
      <button type="button" data-name="${esc(s)}">
        ${esc(s)}
      </button>
    `).join("");

    $("results").innerHTML = `
      <div class="welcome">
        <div class="welcome-icon">🔎</div>
        <h2>No exact match found</h2>
        <p>No species with the common name “${esc(name)}”.</p>
        ${
          hints
            ? `<p class="empty">Try one of these names:</p><div class="suggest">${hints}</div>`
            : `<p class="empty">Check the spelling, or try a shorter start of the name.</p>`
        }
      </div>
    `;

    return;
  }

  const more = r.total_matches > r.matches.length
    ? `<p class="note">Showing ${r.matches.length} of ${r.total_matches} matches.</p>`
    : "";

  $("results").innerHTML = more + r.matches.map(card).join("");
}

function card(m) {
  const sub = [m.infra_rank, m.infra_name]
    .filter(Boolean)
    .join(" ");

  const rows = [
    ["Kingdom", m.kingdom],
    ["Phylum", m.phylum],
    ["Class", m.class],
    ["Order", m.order],
    ["Family", m.family],
    ["Genus", m.genus],
    ["Authority", m.authority],
    ["Population", m.population],
    ["Subspecies or variety", sub],
    ["Taxon ID", m.taxonid]
  ]
    .filter(([, value]) => value !== "" && value !== null && value !== undefined)
    .map(([key, value]) => `
      <dt>${esc(key)}</dt>
      <dd>${esc(value)}</dd>
    `)
    .join("");

  let worse;

  const related = m.more_endangered || [];

  if (related.length) {
    worse = `
      <ol>
        ${related.map((t) => `
          <li>
            ${relatedImageMarkup(t)}
            <span class="who">
              ${
                t.common_name
                  ? `<a data-name="${esc(t.common_name)}" tabindex="0" role="link">${esc(t.common_name)}</a>`
                  : "<b>No common name</b>"
              }
              <em>${esc(t.scientific_name)}</em>
            </span>
            ${chip(t)}
          </li>
        `).join("")}
      </ol>
    `;
  } else {
    worse = `<p class="note">${esc(m.note || "No more threatened related species were found.")}</p>`;
  }

  const image = imageMarkup(
    m.image_url,
    m.common_name || m.scientific_name
  );

  const imageCredit = m.image_link
    ? `<p class="image-credit"><a href="${esc(m.image_link)}" target="_blank" rel="noopener noreferrer">View image search results</a></p>`
    : "";

  return `
    <article class="specimen" style="--s:${statusVar(m.status_code)}">
      <h3>${esc(m.common_name || "Unnamed species")}</h3>
      <p class="sci">${esc(m.scientific_name)}</p>

      ${chip(m)}

      ${image}
      ${imageCredit}

      <dl>${rows}</dl>

      <div class="worse">
        <h4>More threatened in ${esc(m.class || "this group")}</h4>
        ${worse}
      </div>
    </article>
  `;
}

/* Search actions */

$("go").addEventListener("click", () => search());

$("q").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    search();
  }
});

document.querySelectorAll('input[name="mode"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    if ($("q").value.trim()) {
      search();
    }
  });
});

/* Click a suggested or related animal to search for it. */

$("results").addEventListener("click", (event) => {
  const target = event.target.closest("[data-name]");
  if (target) {
    search(target.dataset.name);
  }
});

$("results").addEventListener("keydown", (event) => {
  if (
    (event.key === "Enter" || event.key === " ") &&
    event.target.matches("[data-name]")
  ) {
    event.preventDefault();
    search(event.target.dataset.name);
  }
});

/* Autocomplete suggestions */

let timer;

$("q").addEventListener("input", () => {
  clearTimeout(timer);

  timer = setTimeout(async () => {
    const query = $("q").value.trim();

    if (query.length < 2) {
      $("hints").innerHTML = "";
      return;
    }

    try {
      const response = await fetch(
        `/api/suggest?q=${encodeURIComponent(query)}`
      );

      if (!response.ok) return;

      const list = await response.json();

      $("hints").innerHTML = list
        .map((name) => `<option value="${esc(name)}"></option>`)
        .join("");
    } catch (error) {
      console.error("Autocomplete failed:", error);
    }
  }, 180);
});
