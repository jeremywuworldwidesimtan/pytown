from __future__ import annotations

import argparse
import base64
from io import BytesIO
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from config import TOWN_GENERATION
from mapgen import render_terrain
from towngen import (
    DEFAULT_HEIGHTMAP_PATH,
    export_town_data_to_csv,
    generate_towns,
    project_town_pixels_to_plot,
    project_town_to_plot,
)
from transportgen import (
    DEFAULT_TRANSPORT_NETWORK_PATH,
    DEFAULT_TRANSPORT_OVERLAY_PATH,
    export_transport_routes_to_csv,
    generate_transport_network,
    network_to_dict,
    project_transport_network_to_plot,
    project_transport_overlay_layers_to_plots,
    transport_overlay_png_data_uris,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_PATH = BASE_DIR / "web" / "town_map.html"
DEFAULT_PLOT_OUTPUT_PATH = BASE_DIR / "web" / "town_pixels_only.png"
DEFAULT_TERRAIN_PLOT_OUTPUT_PATH = BASE_DIR / "web" / "town_pixels_overlay.png"
DEFAULT_CSV_OUTPUT_PATH = BASE_DIR / "csv" / "town_data.csv"
DEFAULT_TRANSPORT_CSV_OUTPUT_PATH = BASE_DIR / "csv" / "transport_routes.csv"


def _terrain_png_data_uri(placement_map, max_render_size=1024):
    color_map = render_terrain(
        placement_map.heightmap,
        water_level=placement_map.water_level,
        beach_width=placement_map.beach_width,
    )

    longest_side = max(placement_map.width, placement_map.height)
    stride = max(1, int(np.ceil(longest_side / max_render_size)))
    color_map = np.flipud(color_map[::stride, ::stride])

    image_buffer = BytesIO()
    plt.imsave(image_buffer, color_map, format="png")
    encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _town_footprint_png_data_uri(towns, placement_map, max_render_size=1024):
    longest_side = max(placement_map.width, placement_map.height)
    stride = max(1, int(np.ceil(longest_side / max_render_size)))
    overlay_height = int(np.ceil(placement_map.height / stride))
    overlay_width = int(np.ceil(placement_map.width / stride))
    overlay = np.zeros((overlay_height, overlay_width, 4), dtype=np.uint8)
    size_colors = {
        "Town": (0, 122, 255, 215),
        "City": (0, 92, 230, 220),
        "Metropolis": (0, 65, 210, 225),
        "Megaopolis": (0, 42, 180, 230),
    }

    for town in towns:
        color = size_colors.get(town.size, (0, 122, 255, 215))
        for pixel_x, pixel_y in town.footprint_pixels:
            draw_x = min(pixel_x // stride, overlay_width - 1)
            draw_y = min(pixel_y // stride, overlay_height - 1)
            overlay[overlay_height - 1 - draw_y, draw_x] = color

    image_buffer = BytesIO()
    plt.imsave(image_buffer, overlay, format="png")
    encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _towns_to_dicts(towns, placement_map):
    town_data = []
    for index, town in enumerate(towns):
        screen_x = town.loc_x + (placement_map.width / 2)
        screen_y = (placement_map.height / 2) - town.loc_y
        town_data.append(
            {
                "id": index,
                "name": town.name,
                "size": town.size,
                "display_size": town.display_size,
                "display_specialization": town.display_specialization,
                "specialization": town.specialization,
                "population": town.population,
                "formatted_population": town.formatted_population,
                "density": town.density,
                "area": round(town.area, 2),
                "radius_km": round(town.radius_km, 2),
                "target_area_pixels": town.target_area_pixels,
                "placed_area_pixels": town.placed_area_pixels,
                "est_year": town.est_year,
                "abandoned_year": town.abandoned_year,
                "terrain": town.terrain,
                "loc_x": round(town.loc_x, 2),
                "loc_y": round(town.loc_y, 2),
                "screen_x": round(screen_x, 2),
                "screen_y": round(screen_y, 2),
            }
        )
    return town_data


def build_town_map_html(
    towns,
    placement_map,
    transport_network=None,
    title="Generated Town Map",
    max_render_size=1024,
):
    terrain_image_uri = _terrain_png_data_uri(
        placement_map,
        max_render_size=max_render_size,
    )
    footprint_image_uri = _town_footprint_png_data_uri(
        towns,
        placement_map,
        max_render_size=max_render_size,
    )
    town_data = _towns_to_dicts(towns, placement_map)
    town_count = len(town_data)
    total_population = sum(town["population"] for town in town_data)
    terrain_counts = {
        terrain: sum(1 for town in town_data if town["terrain"] == terrain)
        for terrain in ("beach", "plains", "hills", "mountains", "snow")
    }
    town_size_counts = {
        size: sum(1 for town in town_data if town["size"] == size)
        for size in ("Ghost Town", "Hamlet/Outpost", "Village", "Town", "City", "Metropolis", "Megaopolis")
    }
    transport_summary = network_to_dict(transport_network) if transport_network else None
    transport_overlay_image_uris = (
        transport_overlay_png_data_uris(
            transport_network,
            placement_map,
            max_render_size=max_render_size,
        )
        if transport_network
        else None
    )
    transport_summary_html = ""
    transport_legend_html = ""
    transport_toggle_html = ""
    if transport_summary:
        transport_summary_html = f"""
        <span><strong>{transport_summary["roads"]}</strong>road segments</span>
        <span><strong>{transport_summary["bridges"]}</strong>bridges</span>
        <span><strong>{transport_summary["freeways"]}</strong>freeways</span>
        <span><strong>{transport_summary["railways"]}</strong>railways</span>
        <span><strong>{transport_summary["airways"]}</strong>air routes</span>"""
        transport_legend_html = """
            <span><i class="swatch road"></i>Road</span>
            <span><i class="swatch freeway"></i>Freeway</span>
            <span><i class="swatch railway"></i>Railway</span>
            <span><i class="swatch airway"></i>Air route</span>"""
        transport_toggle_html = """
          <div class="transport-toggles" aria-label="Transport overlays">
            <label><input type="checkbox" data-transport-layer="roads" checked><i class="swatch road"></i>Roads</label>
            <label><input type="checkbox" data-transport-layer="bridges" checked><i class="swatch bridge"></i>Bridges</label>
            <label><input type="checkbox" data-transport-layer="freeways" checked><i class="swatch freeway"></i>Freeways</label>
            <label><input type="checkbox" data-transport-layer="railways" checked><i class="swatch railway"></i>Railways</label>
            <label><input type="checkbox" data-transport-layer="airways" checked><i class="swatch airway"></i>Air routes</label>
          </div>"""

    payload = {
        "towns": town_data,
        "map": {
            "width": placement_map.width,
            "height": placement_map.height,
            "terrain_image_uri": terrain_image_uri,
            "footprint_image_uri": footprint_image_uri,
            "transport_overlay_image_uris": transport_overlay_image_uris,
        },
        "transport": transport_summary,
    }

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7f4;
      --panel: #ffffff;
      --ink: #17201a;
      --muted: #607064;
      --line: #d9e1da;
      --accent: #1f7a68;
      --accent-strong: #0e5749;
      --beach: #d9b46f;
      --plains: #288c4d;
      --hills: #8c542d;
      --selected: #d7263d;
      --shadow: 0 14px 36px rgba(28, 44, 34, 0.12);
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}

    main {{
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }}

    header {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 24px;
      padding: 24px 28px 18px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.82);
    }}

    h1 {{
      margin: 0;
      font-size: 26px;
      line-height: 1.15;
      font-weight: 760;
      letter-spacing: 0;
    }}

    .summary {{
      display: flex;
      gap: 18px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }}

    .summary strong {{
      display: block;
      color: var(--ink);
      font-size: 17px;
      line-height: 1.15;
    }}

    .workspace {{
      display: grid;
      grid-template-columns: minmax(420px, 1fr) minmax(420px, 560px);
      gap: 18px;
      padding: 18px;
      min-height: 0;
    }}

    .map-panel,
    .table-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      min-width: 0;
    }}

    .map-panel {{
      position: relative;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto 1fr;
    }}

    .map-toolbar,
    .table-toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }}

    .legend {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }}

    .legend span {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }}

    .transport-toggles {{
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }}

    .transport-toggles label {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 28px;
      padding: 4px 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfb;
      cursor: pointer;
      user-select: none;
    }}

    .transport-toggles input {{
      margin: 0;
      accent-color: var(--accent);
    }}

    .swatch {{
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--accent);
    }}

    .swatch.beach {{ background: var(--beach); }}
    .swatch.plains {{ background: var(--plains); }}
    .swatch.hills {{ background: var(--hills); }}
    .swatch.town-area {{ background: #007aff; }}
    .swatch.road {{ background: #4b5563; }}
    .swatch.bridge {{ background: #2563eb; }}
    .swatch.freeway {{ background: #f97316; }}
    .swatch.railway {{ background: #111827; }}
    .swatch.airway {{ background: #7c3aed; }}

    .map-shell {{
      position: relative;
      min-height: 580px;
      background: #dce9dd;
    }}

    svg {{
      display: block;
      width: 100%;
      height: 100%;
      min-height: 580px;
    }}

    .terrain-image {{
      image-rendering: auto;
    }}

    .town-footprint-image {{
      image-rendering: pixelated;
      pointer-events: none;
    }}

    .transport-overlay-image {{
      pointer-events: none;
    }}

    .town-point {{
      stroke: #ffffff;
      stroke-width: 7;
      paint-order: stroke;
      cursor: pointer;
      transition: r 120ms ease, fill 120ms ease, opacity 120ms ease;
    }}

    .town-point:hover,
    .town-point:focus,
    .town-point.selected {{
      r: 15;
      fill: var(--selected);
      outline: none;
    }}

    .tooltip {{
      position: fixed;
      z-index: 20;
      pointer-events: none;
      min-width: 210px;
      padding: 10px 12px;
      border-radius: 8px;
      background: rgba(23, 32, 26, 0.94);
      color: #fff;
      font-size: 12px;
      line-height: 1.45;
      opacity: 0;
      transform: translate(12px, 12px);
      transition: opacity 80ms ease;
    }}

    .tooltip.visible {{
      opacity: 1;
    }}

    .tooltip strong {{
      display: block;
      font-size: 14px;
      margin-bottom: 4px;
    }}

    input[type="search"] {{
      width: min(100%, 280px);
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      font: inherit;
      font-size: 13px;
      color: var(--ink);
      background: #fbfcfb;
    }}

    .table-scroll {{
      max-height: calc(100vh - 170px);
      overflow: auto;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}

    th,
    td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
    }}

    th {{
      position: sticky;
      top: 0;
      z-index: 2;
      background: #f9fbf9;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-weight: 720;
    }}

    tbody tr {{
      cursor: pointer;
    }}

    tbody tr:hover,
    tbody tr.selected {{
      background: #edf6f1;
    }}

    .terrain-tag {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      text-transform: capitalize;
    }}

    @media (max-width: 980px) {{
      header {{
        align-items: start;
        flex-direction: column;
      }}

      .workspace {{
        grid-template-columns: 1fr;
      }}

      .map-shell,
      svg {{
        min-height: 420px;
      }}

      .table-scroll {{
        max-height: none;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>{title}</h1>
      </div>
      <div class="summary" aria-label="Town generation summary">
        <span><strong>{town_count}</strong>towns</span>
        <span><strong>{total_population:,}</strong>population</span>
        <span><strong>{terrain_counts["beach"]}</strong>beach</span>
        <span><strong>{terrain_counts["plains"]}</strong>plains</span>
        <span><strong>{terrain_counts["hills"]}</strong>hills</span>
        <span><strong>{terrain_counts["mountains"]}</strong>mountains</span>
        <span><strong>{terrain_counts["snow"]}</strong>snow</span>
        <span><strong>{town_size_counts["Ghost Town"]}</strong>ghost towns</span>
        <span><strong>{town_size_counts["Hamlet/Outpost"]}</strong>hamlets/outposts</span>
        <span><strong>{town_size_counts["Village"]}</strong>villages</span>
        <span><strong>{town_size_counts["Town"]}</strong>towns</span>
        <span><strong>{town_size_counts["City"]}</strong>cities</span>
        <span><strong>{town_size_counts["Metropolis"]}</strong>metropolises</span>
        <span><strong>{town_size_counts["Megaopolis"]}</strong>megaopolises</span>
        {transport_summary_html}
      </div>
    </header>
    <section class="workspace">
      <section class="map-panel" aria-label="Interactive town map">
        <div class="map-toolbar">
          <div class="legend" aria-label="Map legend">
            <span><i class="swatch beach"></i>Beach</span>
            <span><i class="swatch plains"></i>Plains</span>
            <span><i class="swatch hills"></i>Hills</span>
            <span><i class="swatch town-area"></i>Town area</span>
            {transport_legend_html}
            <span><i class="swatch"></i>Town center</span>
          </div>
          {transport_toggle_html}
        </div>
        <div class="map-shell">
          <svg id="town-map" role="img" aria-label="Terrain map with town center points"></svg>
          <div id="tooltip" class="tooltip" role="status"></div>
        </div>
      </section>
      <section class="table-panel" aria-label="Town information table">
        <div class="table-toolbar">
          <strong>Town information</strong>
          <input id="town-search" type="search" placeholder="Search towns, sizes, terrain">
        </div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Size</th>
                <th>Specialization</th>
                <th>Population</th>
                <th>Terrain</th>
                <th>X km</th>
                <th>Y km</th>
              </tr>
            </thead>
            <tbody id="town-table-body"></tbody>
          </table>
        </div>
      </section>
    </section>
  </main>
  <script id="town-map-data" type="application/json">{json.dumps(payload)}</script>
  <script>
    const payload = JSON.parse(document.getElementById("town-map-data").textContent);
    const towns = payload.towns;
    const map = payload.map;
    const svg = document.getElementById("town-map");
    const tooltip = document.getElementById("tooltip");
    const tableBody = document.getElementById("town-table-body");
    const searchInput = document.getElementById("town-search");
    const terrainColors = {{
      beach: "#d9b46f",
      plains: "#288c4d",
      hills: "#8c542d",
      mountains: "#6b7280",
      snow: "#e5edf5",
    }};

    svg.setAttribute("viewBox", `0 0 ${{map.width}} ${{map.height}}`);
    const transportLayers = map.transport_overlay_image_uris || {{}};
    const transportLayerImages = Object.entries(transportLayers).map(([layer, uri]) =>
      `<image class="transport-overlay-image" data-transport-layer="${{layer}}" href="${{uri}}" x="0" y="0" width="${{map.width}}" height="${{map.height}}" preserveAspectRatio="none"></image>`
    ).join("");
    svg.innerHTML = `
      <image class="terrain-image" href="${{map.terrain_image_uri}}" x="0" y="0" width="${{map.width}}" height="${{map.height}}" preserveAspectRatio="none"></image>
      <image class="town-footprint-image" href="${{map.footprint_image_uri}}" x="0" y="0" width="${{map.width}}" height="${{map.height}}" preserveAspectRatio="none"></image>
      ${{transportLayerImages}}
      <g id="town-points"></g>
    `;

    const pointsLayer = document.getElementById("town-points");
    const rowsById = new Map();
    const pointsById = new Map();
    const transportToggles = document.querySelectorAll("[data-transport-layer][type='checkbox']");

    function formatNumber(value) {{
      return new Intl.NumberFormat().format(value);
    }}

    function tooltipHtml(town) {{
      const abandoned = town.abandoned_year ? `Abandoned: ${{town.abandoned_year}}<br>` : "";
      return `<strong>${{town.name}}</strong>
        ${{town.display_size}} on ${{town.terrain}}<br>
        Specialization: ${{town.display_specialization}}<br>
        Population: ${{town.formatted_population}}<br>
        Area: ${{town.area}} sq km<br>
        Footprint radius: ${{town.radius_km}} km<br>
        Town pixels: ${{town.placed_area_pixels}} / ${{town.target_area_pixels}}<br>
        Established: ${{town.est_year}}<br>
        ${{abandoned}}
        Coordinates: (${{town.loc_x}}, ${{town.loc_y}}) km`;
    }}

    function showTooltip(event, town) {{
      tooltip.innerHTML = tooltipHtml(town);
      tooltip.style.left = `${{event.clientX}}px`;
      tooltip.style.top = `${{event.clientY}}px`;
      tooltip.classList.add("visible");
    }}

    function hideTooltip() {{
      tooltip.classList.remove("visible");
    }}

    function selectTown(id, scrollRow = true) {{
      document.querySelectorAll(".selected").forEach((element) => {{
        element.classList.remove("selected");
      }});
      const point = pointsById.get(id);
      const row = rowsById.get(id);
      if (point) point.classList.add("selected");
      if (row) {{
        row.classList.add("selected");
        if (scrollRow) {{
          row.scrollIntoView({{ block: "nearest", behavior: "smooth" }});
        }}
      }}
    }}

    function drawPoints() {{
      towns.forEach((town) => {{
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.classList.add("town-point");
        circle.setAttribute("cx", town.screen_x);
        circle.setAttribute("cy", town.screen_y);
        circle.setAttribute("r", 10);
        circle.setAttribute("fill", terrainColors[town.terrain] || "#1f7a68");
        circle.setAttribute("tabindex", "0");
        circle.setAttribute("role", "button");
        circle.setAttribute("aria-label", `${{town.name}}, ${{town.display_size}}, ${{town.display_specialization}}, ${{town.terrain}}`);
        circle.addEventListener("mousemove", (event) => showTooltip(event, town));
        circle.addEventListener("mouseleave", hideTooltip);
        circle.addEventListener("focus", (event) => showTooltip(event, town));
        circle.addEventListener("blur", hideTooltip);
        circle.addEventListener("click", () => selectTown(town.id));
        circle.addEventListener("keydown", (event) => {{
          if (event.key === "Enter" || event.key === " ") {{
            event.preventDefault();
            selectTown(town.id);
          }}
        }});
        pointsLayer.appendChild(circle);
        pointsById.set(town.id, circle);
      }});
    }}

    function terrainTag(terrain) {{
      const color = terrainColors[terrain] || "#1f7a68";
      return `<span class="terrain-tag"><i class="swatch" style="background:${{color}}"></i>${{terrain}}</span>`;
    }}

    function renderTable(filter = "") {{
      const query = filter.trim().toLowerCase();
      tableBody.innerHTML = "";
      rowsById.clear();

      towns
        .filter((town) => {{
          if (!query) return true;
          return [town.name, town.size, town.display_size, town.display_specialization, town.terrain].some((value) =>
            String(value).toLowerCase().includes(query)
          );
        }})
        .forEach((town) => {{
          const row = document.createElement("tr");
          row.dataset.townId = town.id;
          row.innerHTML = `
            <td>${{town.name}}</td>
            <td>${{town.display_size}}</td>
            <td>${{town.display_specialization}}</td>
            <td>${{formatNumber(town.population)}}</td>
            <td>${{terrainTag(town.terrain)}}</td>
            <td>${{town.loc_x}}</td>
            <td>${{town.loc_y}}</td>
          `;
          row.addEventListener("mouseenter", () => pointsById.get(town.id)?.classList.add("selected"));
          row.addEventListener("mouseleave", () => pointsById.get(town.id)?.classList.remove("selected"));
          row.addEventListener("click", () => selectTown(town.id, false));
          tableBody.appendChild(row);
          rowsById.set(town.id, row);
        }});
    }}

    searchInput.addEventListener("input", (event) => renderTable(event.target.value));
    transportToggles.forEach((toggle) => {{
      toggle.addEventListener("change", () => {{
        const layer = toggle.dataset.transportLayer;
        document.querySelectorAll(`.transport-overlay-image[data-transport-layer="${{layer}}"]`).forEach((image) => {{
          image.style.display = toggle.checked ? "" : "none";
        }});
      }});
    }});
    drawPoints();
    renderTable();
  </script>
</body>
</html>
"""


def write_town_map(
    output_path=DEFAULT_OUTPUT_PATH,
    plot_output_path=DEFAULT_PLOT_OUTPUT_PATH,
    terrain_plot_output_path=None,
    transport_output_path=DEFAULT_TRANSPORT_NETWORK_PATH,
    transport_overlay_output_path=DEFAULT_TRANSPORT_OVERLAY_PATH,
    include_transport=True,
    town_count=TOWN_GENERATION["default_town_count"],
    heightmap_path=DEFAULT_HEIGHTMAP_PATH,
    threshold_km=TOWN_GENERATION["default_spacing_threshold_km"],
    max_attempts=TOWN_GENERATION["default_max_attempts"],
    max_render_size=1024,
):
    towns, placement_map = generate_towns(
        town_count=town_count,
        heightmap_path=heightmap_path,
        threshold_km=threshold_km,
        max_attempts=max_attempts,
    )
    transport_network = (
        generate_transport_network(towns, placement_map) if include_transport else None
    )
    html = build_town_map_html(
        towns,
        placement_map,
        transport_network=transport_network,
        max_render_size=max_render_size,
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    if plot_output_path:
        project_town_pixels_to_plot(
            towns,
            placement_map,
            output_path=plot_output_path,
            show=False,
        )

    if terrain_plot_output_path:
        project_town_to_plot(
            towns,
            placement_map,
            output_path=terrain_plot_output_path,
            show=False,
        )

    if transport_network and transport_output_path:
        project_transport_network_to_plot(
            transport_network,
            placement_map,
            output_path=transport_output_path,
            show=False,
        )

    if transport_network and transport_overlay_output_path:
        project_transport_overlay_layers_to_plots(
            transport_network,
            placement_map,
            output_path=transport_overlay_output_path,
            show=False,
            max_render_size=max_render_size,
        )

    return output_path, towns, placement_map, transport_network


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate towns and export an interactive HTML town map."
    )
    parser.add_argument("--towns", type=int, default=TOWN_GENERATION["default_town_count"])
    parser.add_argument("--heightmap", default=DEFAULT_HEIGHTMAP_PATH)
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--plot-output", default=DEFAULT_PLOT_OUTPUT_PATH)
    parser.add_argument("--terrain-plot-output", default=DEFAULT_TERRAIN_PLOT_OUTPUT_PATH)
    parser.add_argument("--transport-output", default=DEFAULT_TRANSPORT_NETWORK_PATH)
    parser.add_argument("--transport-overlay-output", default=DEFAULT_TRANSPORT_OVERLAY_PATH)
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--no-transport", action="store_true")
    parser.add_argument("--write-terrain-plot", action="store_true")
    parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Export generated town data to CSV.",
    )
    parser.add_argument("--csv-output", default=DEFAULT_CSV_OUTPUT_PATH)
    parser.add_argument(
        "--export-transport-csv",
        action="store_true",
        help="Export generated transport route data to CSV.",
    )
    parser.add_argument(
        "--transport-csv-output",
        default=DEFAULT_TRANSPORT_CSV_OUTPUT_PATH,
    )
    parser.add_argument(
        "--threshold-km",
        type=float,
        default=TOWN_GENERATION["default_spacing_threshold_km"],
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=TOWN_GENERATION["default_max_attempts"],
    )
    parser.add_argument("--max-render-size", type=int, default=1024)
    return parser.parse_args()


def main():
    args = parse_args()
    output_path, towns, placement_map, transport_network = write_town_map(
        output_path=args.output,
        plot_output_path=None if args.no_plot else args.plot_output,
        terrain_plot_output_path=(
            args.terrain_plot_output if args.write_terrain_plot else None
        ),
        transport_output_path=None if args.no_transport else args.transport_output,
        transport_overlay_output_path=(
            None if args.no_transport else args.transport_overlay_output
        ),
        include_transport=not args.no_transport,
        town_count=args.towns,
        heightmap_path=args.heightmap,
        threshold_km=args.threshold_km,
        max_attempts=args.max_attempts,
        max_render_size=args.max_render_size,
    )
    print(f"Generated {len(towns)} towns")
    print(f"Wrote interactive web map to {output_path}")
    if not args.no_plot:
        print(f"Wrote Matplotlib town pixels plot to {args.plot_output}")
    if transport_network:
        summary = network_to_dict(transport_network)
        print(
            "Generated transport network: "
            f"{summary['roads']} roads, "
            f"{summary['bridges']} bridges, "
            f"{summary['freeways']} freeway segments, "
            f"{summary['railways']} railway segments, "
            f"{summary['airways']} air routes"
        )
        print(f"Wrote transport network plot to {args.transport_output}")
        print(f"Wrote transparent transport overlay layers using base path {args.transport_overlay_output}")
    if args.write_terrain_plot:
        print(f"Wrote Matplotlib terrain overlay to {args.terrain_plot_output}")
    if args.export_csv:
        export_town_data_to_csv(towns, args.csv_output)
        print(f"Wrote generated town data CSV to {args.csv_output}")
    if args.export_transport_csv:
        if not transport_network:
            print("Skipped transport route CSV export because transport generation is disabled.")
        else:
            export_transport_routes_to_csv(
                transport_network,
                placement_map,
                args.transport_csv_output,
            )
            print(f"Wrote generated transport route CSV to {args.transport_csv_output}")


if __name__ == "__main__":
    main()
