import {
  ArrowRight,
  Building2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  DollarSign,
  Layers,
  LocateFixed,
  MapPinned,
  Minus,
  Navigation,
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
const DIRECTION_PROFILES = [
  {
    id: "best",
    label: "Best available",
    description: "Roads, bridges, freeways, rail, and flights",
    transports: null,
    color: "#dc2626",
  },
  {
    id: "road",
    label: "Road network",
    description: "Roads, bridges, and freeways",
    transports: "road_network",
    color: "#f97316",
  },
  {
    id: "road-only",
    label: "Standard routes only",
    description: "Toll-free roads only",
    transports: "road",
    color: "#4b5563",
  },
  {
    id: "road-rail",
    label: "Road + rail",
    description: "Road access with railway segments",
    transports: "road_network,railway",
    color: "#0f172a",
  },
  {
    id: "road-flight",
    label: "Road + flight",
    description: "Road access with flight segments",
    transports: "road_network,airway",
    color: "#7c3aed",
  },
  {
    id: "rail",
    label: "Rail only",
    description: "Railway route where connected",
    transports: "railway",
    color: "#111827",
  },
  {
    id: "flight",
    label: "Flight only",
    description: "Direct or connected air route",
    transports: "airway",
    color: "#2563eb",
  },
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

function formatKm(value) {
  if (value === null || value === undefined) return "0 km";
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })} km`;
}

function pathFromCoords(coords) {
  if (!coords?.length) return "";
  return coords.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
}

function buildDirectionPath(option) {
  return option?.steps?.map((step) => pathFromCoords(step.screen_coords)).filter(Boolean) ?? [];
}

function directionSignature(option) {
  return option.steps?.map((step) => step.route_id).join(">") ?? "";
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

function DirectionPlanner({
  towns,
  navigation,
  selectedOption,
  onOriginChange,
  onDestinationChange,
  onSubmit,
  onSwap,
  onClear,
  onSelectOption,
  onSetActiveStep,
}) {
  const activeStep = selectedOption?.steps?.[navigation.activeStepIndex] ?? null;

  return (
    <section className="shrink-0 border-b border-slate-200 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="inline-flex items-center gap-2 text-[12px] font-bold uppercase tracking-normal text-slate-500">
          <Navigation size={15} />
          Directions
        </div>
        {navigation.options.length > 0 && (
          <button
            type="button"
            onClick={onClear}
            className="h-7 rounded-md border border-slate-200 px-2 text-[11px] font-semibold text-slate-600 hover:bg-slate-50"
          >
            Clear
          </button>
        )}
      </div>

      <form className="space-y-2" onSubmit={onSubmit}>
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
          <input
            value={navigation.origin}
            onChange={(event) => onOriginChange(event.target.value)}
            className="h-10 min-w-0 rounded-md border border-slate-200 bg-slate-50 px-3 text-[13px] text-slate-950 outline-none transition focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-100"
            placeholder="From town"
            list="town-direction-options"
            type="search"
          />
          <button
            type="button"
            title="Swap origin and destination"
            onClick={onSwap}
            className="grid h-10 w-10 place-items-center rounded-md border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
          >
            <ArrowRight size={16} />
          </button>
          <input
            value={navigation.destination}
            onChange={(event) => onDestinationChange(event.target.value)}
            className="h-10 min-w-0 rounded-md border border-slate-200 bg-slate-50 px-3 text-[13px] text-slate-950 outline-none transition focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-100"
            placeholder="To town"
            list="town-direction-options"
            type="search"
          />
        </div>
        <datalist id="town-direction-options">
          {towns.map((town) => (
            <option key={town.id} value={town.name} />
          ))}
        </datalist>
        <button
          type="submit"
          disabled={navigation.loading}
          className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-slate-950 px-3 text-[13px] font-semibold text-white transition hover:bg-slate-800 disabled:cursor-wait disabled:bg-slate-400"
        >
          <Route size={16} />
          {navigation.loading ? "Finding routes..." : "Find directions"}
        </button>
      </form>

      {navigation.error && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">
          {navigation.error}
        </div>
      )}

      {navigation.options.length > 0 && (
        <div className="mt-3 space-y-2">
          <div className="text-[11px] font-semibold uppercase tracking-normal text-slate-500">
            Route options
          </div>
          <div className="grid gap-2">
            {navigation.options.map((option) => {
              const selected = selectedOption?.option_id === option.option_id;
              return (
                <button
                  key={option.option_id}
                  type="button"
                  onClick={() => onSelectOption(option.option_id)}
                  className={`rounded-md border p-3 text-left transition ${
                    selected
                      ? "border-blue-400 bg-blue-50 shadow-sm"
                      : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="h-2.5 w-2.5 rounded-full" style={{ background: option.color }} />
                        <span className="truncate text-[13px] font-semibold text-slate-950">{option.label}</span>
                      </div>
                      <div className="mt-0.5 truncate text-[11px] text-slate-500">{option.description}</div>
                    </div>
                    <div className="shrink-0 text-right text-[11px] font-semibold text-slate-600">
                      {option.step_count} steps
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
                    <div>
                      <div className="font-semibold text-slate-950">{formatKm(option.total_distance_km)}</div>
                      <div className="text-slate-500">Distance</div>
                    </div>
                    <div>
                      <div className="font-semibold text-slate-950">{option.eta?.formatted ?? "0m"}</div>
                      <div className="text-slate-500">ETA</div>
                    </div>
                    <div>
                      <div className="font-semibold text-slate-950">{option.formatted_cost ?? option.formatted_toll_cost ?? "$0.00"}</div>
                      <div className="text-slate-500">Cost</div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {selectedOption && (
        <div className="mt-3 rounded-md border border-slate-200 bg-white p-3">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-[13px] font-semibold text-slate-950">{selectedOption.label}</div>
              <div className="text-[11px] text-slate-500">
                Step {Math.min(navigation.activeStepIndex + 1, selectedOption.step_count)} of {selectedOption.step_count}
              </div>
            </div>
            <div className="flex shrink-0 overflow-hidden rounded-md border border-slate-200">
              <button
                type="button"
                title="Previous step"
                className="grid h-8 w-8 place-items-center hover:bg-slate-50 disabled:text-slate-300"
                disabled={navigation.activeStepIndex === 0}
                onClick={() => onSetActiveStep(Math.max(0, navigation.activeStepIndex - 1))}
              >
                <ChevronLeft size={15} />
              </button>
              <button
                type="button"
                title="Next step"
                className="grid h-8 w-8 place-items-center border-l border-slate-200 hover:bg-slate-50 disabled:text-slate-300"
                disabled={navigation.activeStepIndex >= selectedOption.step_count - 1}
                onClick={() => onSetActiveStep(Math.min(selectedOption.step_count - 1, navigation.activeStepIndex + 1))}
              >
                <ChevronRight size={15} />
              </button>
            </div>
          </div>

          {activeStep && (
            <div className="mt-3 rounded-md bg-slate-50 p-3">
              <div className="text-[12px] font-semibold leading-5 text-slate-950">{activeStep.instruction}</div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-slate-600">
                <span className="inline-flex items-center gap-1">
                  <Route size={13} />
                  {formatKm(activeStep.distance_km)}
                </span>
                <span className="inline-flex items-center gap-1">
                  <Clock3 size={13} />
                  {activeStep.formatted_duration}
                </span>
                <span className="inline-flex items-center gap-1">
                  <DollarSign size={13} />
                  {activeStep.formatted_cost ?? activeStep.formatted_toll_cost}
                </span>
              </div>
            </div>
          )}

          <ol className="mt-3 max-h-[260px] space-y-2 overflow-auto pr-1">
            {selectedOption.steps.map((step, index) => {
              const active = index === navigation.activeStepIndex;
              return (
                <li key={`${step.route_id}-${index}`}>
                  <button
                    type="button"
                    onClick={() => onSetActiveStep(index)}
                    className={`w-full rounded-md border px-3 py-2 text-left transition ${
                      active
                        ? "border-blue-300 bg-blue-50"
                        : "border-slate-200 bg-white hover:bg-slate-50"
                    }`}
                  >
                    <div className="text-[12px] font-semibold leading-5 text-slate-950">
                      {index + 1}. {step.instruction}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
                      <span>{formatKm(step.distance_km)}</span>
                      <span>{step.formatted_duration}</span>
                      <span>{step.formatted_cost ?? step.formatted_toll_cost}</span>
                      <span className="capitalize">{step.route_type}</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </section>
  );
}

function Sidebar({
  collapsed,
  map,
  towns,
  selectedTownId,
  search,
  setSearch,
  navigation,
  selectedNavigationOption,
  onSelectTown,
  onOriginChange,
  onDestinationChange,
  onSubmitDirections,
  onSwapDirections,
  onClearDirections,
  onSelectNavigationOption,
  onSetActiveNavigationStep,
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
        <div className="min-h-0 flex-1 overflow-auto">
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

          <DirectionPlanner
            towns={towns}
            navigation={navigation}
            selectedOption={selectedNavigationOption}
            onOriginChange={onOriginChange}
            onDestinationChange={onDestinationChange}
            onSubmit={onSubmitDirections}
            onSwap={onSwapDirections}
            onClear={onClearDirections}
            onSelectOption={onSelectNavigationOption}
            onSetActiveStep={onSetActiveNavigationStep}
          />

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
        </div>
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
  navigationOptions,
  selectedNavigationOption,
  activeNavigationStepIndex,
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
  const visibleNavigationOptions = useMemo(() => {
    if (selectedNavigationOption) return [selectedNavigationOption];
    return navigationOptions;
  }, [navigationOptions, selectedNavigationOption]);

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

          {visibleNavigationOptions.length > 0 && (
            <g pointerEvents="none">
              {visibleNavigationOptions.map((option, optionIndex) => {
                const selected = selectedNavigationOption?.option_id === option.option_id;
                const opacity = selectedNavigationOption && !selected ? 0 : selected ? 1 : 0.78;
                return (
                  <g key={option.option_id} opacity={opacity}>
                    {buildDirectionPath(option).map((pathData, segmentIndex) => {
                      const active = selected && segmentIndex === activeNavigationStepIndex;
                      return (
                        <g key={`${option.option_id}-${segmentIndex}`}>
                          <path
                            data-nav-route={option.option_id}
                            data-nav-segment={segmentIndex}
                            data-nav-backdrop="true"
                            d={pathData}
                            fill="none"
                            stroke="white"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={active ? 18 : selected ? 14 : 11}
                            vectorEffect="non-scaling-stroke"
                          />
                          <path
                            data-nav-route={option.option_id}
                            data-nav-segment={segmentIndex}
                            data-nav-active={active ? "true" : "false"}
                            d={pathData}
                            fill="none"
                            stroke={active ? "#facc15" : option.color}
                            strokeDasharray={selected ? "" : optionIndex % 2 === 0 ? "" : "16 10"}
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={active ? 10 : selected ? 8 : 5}
                            vectorEffect="non-scaling-stroke"
                          />
                        </g>
                      );
                    })}
                  </g>
                );
              })}
            </g>
          )}

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
  const [navigation, setNavigation] = useState({
    origin: "",
    destination: "",
    loading: false,
    error: null,
    options: [],
    selectedOptionId: null,
    activeStepIndex: 0,
  });

  const selectedNavigationOption = useMemo(
    () => navigation.options.find((option) => option.option_id === navigation.selectedOptionId) ?? null,
    [navigation.options, navigation.selectedOptionId],
  );

  useEffect(() => {
    if (selectedTownId === null && towns.length) {
      setSelectedTownId(towns[0].id);
    }
  }, [selectedTownId, towns]);

  useEffect(() => {
    if (!towns.length) return;
    setNavigation((current) => {
      if (current.origin || current.destination) return current;
      return {
        ...current,
        origin: towns[0]?.name ?? "",
        destination: towns[1]?.name ?? "",
      };
    });
  }, [towns]);

  async function loadDirectionOption(profile, origin, destination) {
    const params = new URLSearchParams({ from: origin, to: destination });
    if (profile.transports) {
      params.set("transports", profile.transports);
    }
    const response = await fetch(`${API_ROOT}/api/directions?${params.toString()}`);
    if (!response.ok) return null;
    const data = await response.json();
    return {
      ...data,
      option_id: profile.id,
      profile_id: profile.id,
      label: profile.label,
      description: profile.description,
      color: profile.color,
      signature: directionSignature(data),
    };
  }

  async function handleSubmitDirections(event) {
    event.preventDefault();
    const origin = navigation.origin.trim();
    const destination = navigation.destination.trim();
    if (!origin || !destination) {
      setNavigation((current) => ({
        ...current,
        error: "Choose both an origin and a destination town.",
      }));
      return;
    }

    setNavigation((current) => ({
      ...current,
      loading: true,
      error: null,
      options: [],
      selectedOptionId: null,
      activeStepIndex: 0,
    }));

    try {
      const settled = await Promise.allSettled(
        DIRECTION_PROFILES.map((profile) => loadDirectionOption(profile, origin, destination)),
      );
      const options = [];
      const seen = new Set();
      for (const result of settled) {
        if (result.status !== "fulfilled" || !result.value) continue;
        const option = result.value;
        const signature = option.signature || `${option.total_distance_km}-${option.step_count}-${option.cost}`;
        if (option.profile_id !== "best" && seen.has(signature)) continue;
        seen.add(signature);
        options.push(option);
      }

      setNavigation((current) => ({
        ...current,
        loading: false,
        error: options.length ? null : "No direction options found for those towns.",
        options,
        selectedOptionId: null,
        activeStepIndex: 0,
      }));
    } catch (error) {
      setNavigation((current) => ({
        ...current,
        loading: false,
        error: error instanceof Error ? error.message : "Unable to fetch directions.",
      }));
    }
  }

  function clearDirections() {
    setNavigation((current) => ({
      ...current,
      error: null,
      options: [],
      selectedOptionId: null,
      activeStepIndex: 0,
    }));
  }

  function selectNavigationOption(optionId) {
    setNavigation((current) => ({
      ...current,
      selectedOptionId: optionId,
      activeStepIndex: 0,
    }));
  }

  function setActiveNavigationStep(index) {
    setNavigation((current) => ({
      ...current,
      activeStepIndex: index,
    }));
  }

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
        navigation={navigation}
        selectedNavigationOption={selectedNavigationOption}
        onSelectTown={setSelectedTownId}
        onOriginChange={(value) => setNavigation((current) => ({ ...current, origin: value }))}
        onDestinationChange={(value) => setNavigation((current) => ({ ...current, destination: value }))}
        onSubmitDirections={handleSubmitDirections}
        onSwapDirections={() =>
          setNavigation((current) => ({
            ...current,
            origin: current.destination,
            destination: current.origin,
          }))
        }
        onClearDirections={clearDirections}
        onSelectNavigationOption={selectNavigationOption}
        onSetActiveNavigationStep={setActiveNavigationStep}
        onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
      />
      <MapCanvas
        map={map}
        towns={towns}
        routes={routes}
        visibleLayers={visibleLayers}
        setVisibleLayers={setVisibleLayers}
        selectedTownId={selectedTownId}
        navigationOptions={navigation.options}
        selectedNavigationOption={selectedNavigationOption}
        activeNavigationStepIndex={navigation.activeStepIndex}
        onSelectTown={setSelectedTownId}
      />
    </div>
  );
}
