import {
  Building2,
  ChevronLeft,
  ChevronRight,
  Layers,
  LocateFixed,
  MapPinned,
  Minus,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RotateCcw,
  Route,
  Search,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

const MAP_SIZE = 4096;
const API_ROOT = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const TERRAIN_COLORS = {
  beach: "#d9b46f",
  plains: "#288c4d",
  hills: "#8c542d",
  mountains: "#6b7280",
  snow: "#e5edf5",
};

const TRANSPORT_LAYERS = [
  { id: "road", label: "Roads", color: "#4b5563", width: 4, dash: "" },
  { id: "bridge", label: "Bridges", color: "#2563eb", width: 7, dash: "" },
  { id: "freeway", label: "Freeways", color: "#f97316", width: 6, dash: "" },
  { id: "railway", label: "Railways", color: "#111827", width: 4, dash: "18 10" },
  { id: "airway", label: "Air routes", color: "#7c3aed", width: 3, dash: "12 18" },
];

const INITIAL_VISIBLE_LAYERS = {
  townPixels: true,
  road: true,
  bridge: true,
  freeway: true,
  railway: true,
  airway: false,
};

function formatNumber(value) {
  return new Intl.NumberFormat().format(value ?? 0);
}

function pathFromCoords(coords) {
  if (!coords?.length) return "";
  return coords.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function usePyTownData() {
  const [state, setState] = useState({
    map: null,
    towns: [],
    routes: [],
    loading: true,
    error: null,
  });

  useEffect(() => {
    let active = true;

    async function loadData() {
      try {
        const [mapResponse, townsResponse, routesResponse] = await Promise.all([
          fetch(`${API_ROOT}/api/map`),
          fetch(`${API_ROOT}/api/towns?limit=5000`),
          fetch(`${API_ROOT}/api/transport-routes`),
        ]);

        if (!mapResponse.ok || !townsResponse.ok || !routesResponse.ok) {
          throw new Error("Unable to load PyTown map data.");
        }

        const [map, townsPayload, routesPayload] = await Promise.all([
          mapResponse.json(),
          townsResponse.json(),
          routesResponse.json(),
        ]);

        if (active) {
          setState({
            map,
            towns: townsPayload.towns,
            routes: routesPayload.routes,
            loading: false,
            error: null,
          });
        }
      } catch (error) {
        if (active) {
          setState((current) => ({
            ...current,
            loading: false,
            error: error instanceof Error ? error.message : "Unknown error",
          }));
        }
      }
    }

    loadData();
    return () => {
      active = false;
    };
  }, []);

  return state;
}

function SummaryMetric({ label, value }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-semibold uppercase tracking-normal text-slate-500">{label}</div>
      <div className="truncate text-[18px] font-semibold leading-tight text-slate-950">{value}</div>
    </div>
  );
}

function LayerButton({ layer, enabled, onToggle }) {
  return (
    <button
      type="button"
      title={`${enabled ? "Hide" : "Show"} ${layer.label}`}
      onClick={onToggle}
      className={`inline-flex h-9 items-center gap-2 rounded-md border px-3 text-[12px] font-semibold transition ${
        enabled
          ? "border-slate-300 bg-white text-slate-950 shadow-sm"
          : "border-slate-200 bg-slate-50 text-slate-500"
      }`}
    >
      <span className="h-2.5 w-2.5 rounded-full" style={{ background: layer.color }} />
      {layer.label}
    </button>
  );
}

function Sidebar({
  collapsed,
  map,
  towns,
  selectedTownId,
  search,
  setSearch,
  onSelectTown,
  onToggleSidebar,
}) {
  const filteredTowns = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return towns;
    return towns.filter((town) =>
      [town.name, town.size, town.display_specialization, town.terrain]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query)),
    );
  }, [search, towns]);

  const transportCounts = map?.summary?.transport_counts ?? {};
  const terrainCounts = map?.summary?.terrain_counts ?? {};

  return (
    <aside
      className={`z-20 flex h-full min-h-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200 ${
        collapsed ? "w-[64px]" : "w-[430px]"
      }`}
    >
      <div className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 px-3">
        <button
          type="button"
          title={collapsed ? "Open sidebar" : "Collapse sidebar"}
          onClick={onToggleSidebar}
          className="grid h-9 w-9 place-items-center rounded-md border border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
        >
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
        {!collapsed && (
          <div className="min-w-0">
            <h1 className="truncate text-[19px] font-semibold leading-tight text-slate-950">PyTown Map</h1>
            <p className="truncate text-[12px] text-slate-500">Generated terrain, towns, and transport network</p>
          </div>
        )}
      </div>

      {collapsed ? (
        <div className="flex flex-1 flex-col items-center gap-3 py-4 text-slate-500">
          <MapPinned size={22} />
          <Building2 size={22} />
          <Route size={22} />
        </div>
      ) : (
        <>
          <div className="shrink-0 border-b border-slate-200 p-4">
            <div className="grid grid-cols-2 gap-4">
              <SummaryMetric label="Towns" value={formatNumber(map?.summary?.town_count)} />
              <SummaryMetric label="Population" value={map?.summary?.formatted_total_population ?? "0"} />
              <SummaryMetric label="Routes" value={formatNumber(Object.values(transportCounts).reduce((a, b) => a + b, 0))} />
              <SummaryMetric label="Map" value={`${MAP_SIZE} px`} />
            </div>

            <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-[12px] text-slate-600">
              {Object.entries(terrainCounts).map(([terrain, count]) => (
                <div key={terrain} className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-2 capitalize">
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ background: TERRAIN_COLORS[terrain] ?? "#64748b" }}
                    />
                    {terrain}
                  </span>
                  <strong className="font-semibold text-slate-900">{count}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="shrink-0 border-b border-slate-200 p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className="h-10 w-full rounded-md border border-slate-200 bg-slate-50 pl-9 pr-3 text-[13px] text-slate-950 outline-none transition focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-100"
                placeholder="Search towns, sizes, terrain"
                type="search"
              />
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full border-collapse text-[12px]">
              <thead className="sticky top-0 z-10 bg-slate-50 text-left text-[10px] font-bold uppercase tracking-normal text-slate-500">
                <tr>
                  <th className="border-b border-slate-200 px-3 py-2">Name</th>
                  <th className="border-b border-slate-200 px-3 py-2">Size</th>
                  <th className="border-b border-slate-200 px-3 py-2">Population</th>
                  <th className="border-b border-slate-200 px-3 py-2">Terrain</th>
                </tr>
              </thead>
              <tbody>
                {filteredTowns.map((town) => (
                  <tr
                    key={town.id}
                    onClick={() => onSelectTown(town.id)}
                    className={`cursor-pointer border-b border-slate-100 hover:bg-blue-50 ${
                      selectedTownId === town.id ? "bg-blue-100" : ""
                    }`}
                  >
                    <td className="max-w-[150px] truncate px-3 py-2 font-semibold text-slate-950" title={town.name}>
                      {town.name}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-600">{town.display_size}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-600">{town.formatted_population}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-600">
                      <span className="inline-flex items-center gap-1.5 capitalize">
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{ background: TERRAIN_COLORS[town.terrain] ?? "#64748b" }}
                        />
                        {town.terrain}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </aside>
  );
}

function MapControls({ zoom, onZoomIn, onZoomOut, onReset, onLocate }) {
  return (
    <div className="absolute right-4 top-4 z-20 flex flex-col overflow-hidden rounded-md border border-slate-200 bg-white shadow-control">
      <button type="button" title="Zoom in" className="grid h-10 w-10 place-items-center hover:bg-slate-50" onClick={onZoomIn}>
        <Plus size={18} />
      </button>
      <div className="h-px bg-slate-200" />
      <button type="button" title="Zoom out" className="grid h-10 w-10 place-items-center hover:bg-slate-50" onClick={onZoomOut}>
        <Minus size={18} />
      </button>
      <div className="h-px bg-slate-200" />
      <button type="button" title="Reset view" className="grid h-10 w-10 place-items-center hover:bg-slate-50" onClick={onReset}>
        <RotateCcw size={17} />
      </button>
      <div className="h-px bg-slate-200" />
      <button type="button" title="Center selected town" className="grid h-10 w-10 place-items-center hover:bg-slate-50" onClick={onLocate}>
        <LocateFixed size={17} />
      </button>
      <div className="border-t border-slate-200 px-1 py-1 text-center text-[10px] font-semibold text-slate-500">
        {Math.round(zoom * 100)}%
      </div>
    </div>
  );
}

function TownDetail({ town, onPrevious, onNext }) {
  if (!town) return null;

  return (
    <div className="absolute bottom-4 left-4 z-20 w-[min(360px,calc(100%-32px))] rounded-md border border-slate-200 bg-white p-4 shadow-map">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-[18px] font-semibold leading-tight text-slate-950">{town.name}</h2>
          <p className="mt-1 text-[12px] text-slate-500">
            {town.display_size} · {town.display_specialization} · {town.terrain}
          </p>
        </div>
        <div className="flex shrink-0 overflow-hidden rounded-md border border-slate-200">
          <button type="button" title="Previous town" className="grid h-8 w-8 place-items-center hover:bg-slate-50" onClick={onPrevious}>
            <ChevronLeft size={16} />
          </button>
          <button type="button" title="Next town" className="grid h-8 w-8 place-items-center border-l border-slate-200 hover:bg-slate-50" onClick={onNext}>
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        <SummaryMetric label="Population" value={town.formatted_population} />
        <SummaryMetric label="Area" value={`${town.area} km²`} />
        <SummaryMetric label="Pixels" value={`${town.placed_area_pixels}/${town.target_area_pixels}`} />
      </div>
      <div className="mt-3 text-[12px] leading-5 text-slate-600">
        Established {town.est_year}
        {town.abandoned_year ? `, abandoned ${town.abandoned_year}` : ""}. Coordinates {town.loc_x}, {town.loc_y} km.
      </div>
    </div>
  );
}

function MapCanvas({
  map,
  towns,
  routes,
  visibleLayers,
  setVisibleLayers,
  selectedTownId,
  onSelectTown,
}) {
  const viewportRef = useRef(null);
  const dragRef = useRef(null);
  const [view, setView] = useState({ scale: 0.22, x: 180, y: -150 });

  const selectedTown = useMemo(
    () => towns.find((town) => town.id === selectedTownId) ?? null,
    [selectedTownId, towns],
  );

  const routesByLayer = useMemo(() => {
    return routes.reduce((groups, route) => {
      groups[route.route_type] ??= [];
      groups[route.route_type].push(route);
      return groups;
    }, {});
  }, [routes]);

  function updateScale(nextScale) {
    setView((current) => ({ ...current, scale: clamp(nextScale, 0.14, 2.8) }));
  }

  function resetView() {
    setView({ scale: 0.22, x: 180, y: -150 });
  }

  function centerOnTown(town = selectedTown) {
    if (!town || !viewportRef.current) return;
    const rect = viewportRef.current.getBoundingClientRect();
    setView((current) => ({
      ...current,
      scale: Math.max(current.scale, 0.52),
      x: rect.width / 2 - town.screen_x * Math.max(current.scale, 0.52),
      y: rect.height / 2 - town.screen_y * Math.max(current.scale, 0.52),
    }));
  }

  function selectAdjacent(direction) {
    if (!towns.length) return;
    const index = Math.max(0, towns.findIndex((town) => town.id === selectedTownId));
    const nextTown = towns[(index + direction + towns.length) % towns.length];
    onSelectTown(nextTown.id);
    window.requestAnimationFrame(() => centerOnTown(nextTown));
  }

  function handlePointerDown(event) {
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      viewX: view.x,
      viewY: view.y,
    };
  }

  function handlePointerMove(event) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setView((current) => ({
      ...current,
      x: drag.viewX + event.clientX - drag.startX,
      y: drag.viewY + event.clientY - drag.startY,
    }));
  }

  function handlePointerUp(event) {
    if (dragRef.current?.pointerId === event.pointerId) {
      dragRef.current = null;
    }
  }

  function handleWheel(event) {
    event.preventDefault();
    const delta = event.deltaY > 0 ? -0.08 : 0.08;
    updateScale(view.scale + delta);
  }

  function selectTownFromMarker(event, town) {
    event.stopPropagation();
    onSelectTown(town.id);
  }

  function handleTownMarkerKeyDown(event, town) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectTownFromMarker(event, town);
    }
  }

  return (
    <main className="relative min-w-0 flex-1 overflow-hidden bg-[#d7e2d7]">
      <div className="absolute left-4 top-4 z-20 flex max-w-[calc(100%-96px)] flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setVisibleLayers((layers) => ({ ...layers, townPixels: !layers.townPixels }))}
          className={`inline-flex h-9 items-center gap-2 rounded-md border px-3 text-[12px] font-semibold shadow-control transition ${
            visibleLayers.townPixels
              ? "border-slate-300 bg-white text-slate-950"
              : "border-slate-200 bg-slate-50 text-slate-500"
          }`}
        >
          <Layers size={15} />
          Town pixels
        </button>
        {TRANSPORT_LAYERS.map((layer) => (
          <LayerButton
            key={layer.id}
            layer={layer}
            enabled={visibleLayers[layer.id]}
            onToggle={() => setVisibleLayers((layers) => ({ ...layers, [layer.id]: !layers[layer.id] }))}
          />
        ))}
      </div>

      <MapControls
        zoom={view.scale}
        onZoomIn={() => updateScale(view.scale + 0.16)}
        onZoomOut={() => updateScale(view.scale - 0.16)}
        onReset={resetView}
        onLocate={() => centerOnTown()}
      />

      <div
        ref={viewportRef}
        className="absolute inset-0 cursor-grab touch-none active:cursor-grabbing"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onWheel={handleWheel}
      >
        <svg
          className="map-stage absolute left-0 top-0"
          width={MAP_SIZE}
          height={MAP_SIZE}
          viewBox={`0 0 ${MAP_SIZE} ${MAP_SIZE}`}
          style={{
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
          }}
          role="img"
          aria-label="Generated PyTown terrain map"
        >
          <image href={`${API_ROOT}${map.images.terrain}`} x="0" y="0" width={MAP_SIZE} height={MAP_SIZE} preserveAspectRatio="none" />
          {visibleLayers.townPixels && (
            <image
              href={`${API_ROOT}${map.images.town_footprints}`}
              x="0"
              y="0"
              width={MAP_SIZE}
              height={MAP_SIZE}
              preserveAspectRatio="none"
              className="pointer-events-none"
            />
          )}

          {TRANSPORT_LAYERS.map((layer) => (
            <g key={layer.id} opacity={visibleLayers[layer.id] ? 0.88 : 0} pointerEvents="none">
              {(routesByLayer[layer.id] ?? []).map((route) => (
                <path
                  key={route.route_id}
                  d={pathFromCoords(route.screen_coords)}
                  fill="none"
                  stroke={layer.color}
                  strokeDasharray={layer.dash}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={layer.width}
                  vectorEffect="non-scaling-stroke"
                />
              ))}
            </g>
          ))}

          <g>
            {towns.map((town) => {
              const selected = selectedTownId === town.id;
              return (
                <g
                  key={town.id}
                  className="town-marker cursor-pointer"
                  role="button"
                  tabIndex={0}
                  aria-label={`${town.name}, ${town.display_size}, ${town.formatted_population} population`}
                  onPointerDown={(event) => event.stopPropagation()}
                  onPointerMove={(event) => event.stopPropagation()}
                  onPointerUp={(event) => event.stopPropagation()}
                  onClick={(event) => selectTownFromMarker(event, town)}
                  onKeyDown={(event) => handleTownMarkerKeyDown(event, town)}
                >
                  <circle
                    cx={town.screen_x}
                    cy={town.screen_y}
                    r={22}
                    fill="transparent"
                    stroke="transparent"
                    pointerEvents="all"
                    vectorEffect="non-scaling-stroke"
                  />
                  <circle
                    cx={town.screen_x}
                    cy={town.screen_y}
                    r={selected ? 16 : 9}
                    fill={selected ? "#d7263d" : TERRAIN_COLORS[town.terrain] ?? "#0f766e"}
                    stroke="white"
                    strokeWidth={selected ? 7 : 5}
                    vectorEffect="non-scaling-stroke"
                    className="transition-[r,fill] duration-100"
                    pointerEvents="none"
                  />
                  <title>
                    {town.name} · {town.display_size} · {town.formatted_population}
                  </title>
                </g>
              );
            })}
          </g>
        </svg>
      </div>

      <TownDetail
        town={selectedTown}
        onPrevious={() => selectAdjacent(-1)}
        onNext={() => selectAdjacent(1)}
      />
    </main>
  );
}

export default function App() {
  const { map, towns, routes, loading, error } = usePyTownData();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedTownId, setSelectedTownId] = useState(null);
  const [visibleLayers, setVisibleLayers] = useState(INITIAL_VISIBLE_LAYERS);

  useEffect(() => {
    if (selectedTownId === null && towns.length) {
      setSelectedTownId(towns[0].id);
    }
  }, [selectedTownId, towns]);

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center bg-slate-100 text-[14px] font-semibold text-slate-600">
        Loading PyTown map...
      </div>
    );
  }

  if (error || !map) {
    return (
      <div className="grid min-h-screen place-items-center bg-slate-100 p-6 text-center">
        <div className="rounded-md border border-red-200 bg-white p-5 text-[14px] text-red-700 shadow-map">
          {error ?? "Unable to load PyTown map."}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen min-h-0 overflow-hidden bg-slate-100 text-slate-950">
      <Sidebar
        collapsed={sidebarCollapsed}
        map={map}
        towns={towns}
        selectedTownId={selectedTownId}
        search={search}
        setSearch={setSearch}
        onSelectTown={setSelectedTownId}
        onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
      />
      <MapCanvas
        map={map}
        towns={towns}
        routes={routes}
        visibleLayers={visibleLayers}
        setVisibleLayers={setVisibleLayers}
        selectedTownId={selectedTownId}
        onSelectTown={setSelectedTownId}
      />
    </div>
  );
}
