from __future__ import annotations

import base64
from collections import defaultdict
import heapq
import json
import re
import sqlite3
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Iterable

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from PIL import Image

from config import TRANSPORT_ROUTING


BASE_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = BASE_DIR / "api" / "database.db"
WORLD_RENDER_PATH = BASE_DIR / "csv" / "world_render.png"
TOWN_MAP_HTML_PATH = BASE_DIR / "web" / "town_map.html"
TRANSPORT_OVERLAY_DIR = BASE_DIR / "web"

MAP_WIDTH = 4096
MAP_HEIGHT = 4096
TRANSPORT_LAYERS = ("road", "bridge", "freeway", "railway", "airway")
ROAD_NETWORK_TYPES = ("road", "bridge", "freeway")
ROUTE_TYPE_ALIASES = {
    "roads": ("road", "bridge"),
    "road-network": ROAD_NETWORK_TYPES,
    "road_network": ROAD_NETWORK_TYPES,
    "roadnetwork": ROAD_NETWORK_TYPES,
    "driving": ROAD_NETWORK_TYPES,
    "drive": ROAD_NETWORK_TYPES,
    "rail": ("railway",),
    "rails": ("railway",),
    "train": ("railway",),
    "trains": ("railway",),
    "flight": ("airway",),
    "flights": ("airway",),
    "air": ("airway",),
    "airways": ("airway",),
}
ROUTE_TYPE_PRIORITY = {
    "airway": 0,
    "railway": 1,
    "freeway": 2,
    "bridge": 3,
    "road": 4,
}


app = FastAPI(title="PyTown API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _connect() -> sqlite3.Connection:
    if not DATABASE_PATH.exists():
        raise HTTPException(status_code=500, detail="Database not found.")
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _screen_x(x_coordinate: float) -> float:
    return round(x_coordinate + (MAP_WIDTH / 2), 2)


def _screen_y(y_coordinate: float) -> float:
    return round((MAP_HEIGHT / 2) - y_coordinate, 2)


def _format_number(value: int | float | None) -> str:
    if value is None:
        return ""
    return f"{value:,.0f}"


def _display_specialization(value: str | None) -> str:
    return value if value else "Unspecified"


def _town_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "size": row["size"],
        "display_size": row["size"],
        "specialization": row["specialization"],
        "display_specialization": _display_specialization(row["specialization"]),
        "population": row["population"],
        "formatted_population": _format_number(row["population"]),
        "density": row["density"],
        "area": round(row["area_sq_km"], 2),
        "radius_km": round(row["radius_km"], 2),
        "target_area_pixels": row["target_area_pixels"],
        "placed_area_pixels": row["placed_area_pixels"],
        "est_year": row["established_year"],
        "abandoned_year": row["abandoned_year"],
        "terrain": row["terrain"],
        "loc_x": round(row["x_coordinate"], 2),
        "loc_y": round(row["y_coordinate"], 2),
        "screen_x": _screen_x(row["x_coordinate"]),
        "screen_y": _screen_y(row["y_coordinate"]),
    }


def _route_from_row(row: sqlite3.Row) -> dict:
    return {
        "route_id": row["route_id"],
        "route_type": row["route_type"],
        "edge_id": row["edge_id"],
        "from_town_id": row["from_town_id"],
        "from_town_name": row["from_town_name"],
        "to_town_id": row["to_town_id"],
        "to_town_name": row["to_town_name"],
        "distance_km": row["distance_km"],
        "is_bridge": bool(row["is_bridge"]),
        "route_coords": json.loads(row["route_coords_json"]),
        "screen_coords": json.loads(row["screen_coords_json"]),
    }


def _town_reference(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "size": row["size"],
        "terrain": row["terrain"],
        "loc_x": round(row["x_coordinate"], 2),
        "loc_y": round(row["y_coordinate"], 2),
    }


def _round_distance(value: float) -> float:
    return round(value, 3)


def _round_duration(value: float) -> float:
    return round(value, 3)


def _round_money(value: float) -> float:
    return round(value, 2)


def _format_money(value: float) -> str:
    return f"${_round_money(value):,.2f}"


def _format_duration(hours: float) -> str:
    total_minutes = int(round(hours * 60))
    days, remainder = divmod(total_minutes, 24 * 60)
    whole_hours, minutes = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if whole_hours or days:
        parts.append(f"{whole_hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _speed_limit_kmh(route_type: str) -> float:
    return float(TRANSPORT_ROUTING["speed_limits_kmh"][route_type])


def _edge_duration_hours(edge: dict) -> float:
    return edge["distance_km"] / _speed_limit_kmh(edge["route_type"])


def _cost_settings(route_type: str) -> dict:
    return TRANSPORT_ROUTING["costs"].get(route_type, {})


def _is_freeway_city_entry(edge: dict, town_lookup: dict[int, dict]) -> bool:
    if edge["route_type"] != "freeway":
        return False

    toll_settings = _cost_settings("freeway")
    to_town = town_lookup[edge["to_town_id"]]
    return to_town["size"] in set(toll_settings["tolled_city_sizes"])


def _edge_cost_details(edge: dict, town_lookup: dict[int, dict]) -> dict:
    route_type = edge["route_type"]
    settings = _cost_settings(route_type)
    components = {}

    if route_type == "freeway":
        components["distance"] = edge["distance_km"] * float(settings["per_km_rate"])
        if _is_freeway_city_entry(edge, town_lookup):
            components["city_entry_fee"] = float(settings["city_entry_fee"])
    elif route_type == "bridge":
        components["distance"] = edge["distance_km"] * float(settings["per_km_rate"])
        components["base_fee"] = float(settings["base_fee"])
    elif route_type == "railway":
        components["distance"] = edge["distance_km"] * float(settings["per_km_rate"])
        components["station_fee"] = float(settings["station_fee"])
    elif route_type == "airway":
        components["distance"] = edge["distance_km"] * float(settings["per_km_rate"])
        components["departure_fee"] = float(settings["departure_fee"])

    return {
        "amount": sum(components.values()),
        "components": {
            name: _round_money(value)
            for name, value in components.items()
            if value > 0
        },
        "freeway_city_entry_fee_applied": _is_freeway_city_entry(edge, town_lookup),
        "railway_station_fee_applied": route_type == "railway",
        "flight_departure_fee_applied": route_type == "airway",
    }


def _edge_transport_cost(edge: dict, town_lookup: dict[int, dict]) -> float:
    return float(_edge_cost_details(edge, town_lookup)["amount"])


def _parse_route_types(value: str | None) -> tuple[str, ...]:
    if not value:
        return TRANSPORT_LAYERS

    route_types: list[str] = []
    unknown: list[str] = []
    for raw_token in value.split(","):
        token = raw_token.strip().lower()
        if not token:
            continue
        expanded = ROUTE_TYPE_ALIASES.get(token)
        if expanded is None and token in TRANSPORT_LAYERS:
            expanded = (token,)
        if expanded is None:
            unknown.append(token)
            continue
        for route_type in expanded:
            if route_type not in route_types:
                route_types.append(route_type)

    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown transport type(s): {', '.join(sorted(unknown))}",
        )
    if not route_types:
        raise HTTPException(status_code=400, detail="At least one transport type is required.")
    return tuple(route_types)


def _resolve_town(conn: sqlite3.Connection, value: str, label: str) -> sqlite3.Row:
    token = value.strip()
    if not token:
        raise HTTPException(status_code=400, detail=f"{label} location is required.")

    if token.isdigit():
        row = conn.execute("SELECT * FROM towns WHERE id = ?", (int(token),)).fetchone()
        if row is not None:
            return row

    exact = conn.execute(
        "SELECT * FROM towns WHERE LOWER(name) = LOWER(?) ORDER BY population DESC, name",
        (token,),
    ).fetchall()
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"{label} location is ambiguous.",
                "matches": [_town_reference(row) for row in exact[:10]],
            },
        )

    matches = conn.execute(
        """
        SELECT *
        FROM towns
        WHERE LOWER(name) LIKE LOWER(?)
        ORDER BY
            CASE WHEN LOWER(name) LIKE LOWER(?) THEN 0 ELSE 1 END,
            population DESC,
            name
        LIMIT 11
        """,
        (f"%{token}%", f"{token}%"),
    ).fetchall()
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"{label} location is ambiguous.",
                "matches": [_town_reference(row) for row in matches[:10]],
            },
        )
    raise HTTPException(status_code=404, detail=f"{label} location not found.")


def _route_type_penalty(route_type: str) -> int:
    return ROUTE_TYPE_PRIORITY.get(route_type, 10)


def _directed_edge(row: sqlite3.Row, from_town_id: int, to_town_id: int) -> dict:
    reverse = from_town_id != row["from_town_id"]
    route_coords = json.loads(row["route_coords_json"])
    screen_coords = json.loads(row["screen_coords_json"])
    if reverse:
        route_coords.reverse()
        screen_coords.reverse()

    return {
        "route_id": row["route_id"],
        "route_type": row["route_type"],
        "edge_id": row["edge_id"],
        "from_town_id": from_town_id,
        "to_town_id": to_town_id,
        "distance_km": float(row["distance_km"]),
        "is_bridge": bool(row["is_bridge"]),
        "route_coords": route_coords,
        "screen_coords": screen_coords,
    }


def _shortest_transport_path(
    conn: sqlite3.Connection,
    source_town_id: int,
    target_town_id: int,
    route_types: tuple[str, ...],
) -> tuple[float, list[dict]]:
    if source_town_id == target_town_id:
        return 0.0, []

    placeholders = ",".join("?" for _ in route_types)
    rows = conn.execute(
        f"""
        SELECT *
        FROM transport_routes
        WHERE route_type IN ({placeholders})
        """,
        route_types,
    ).fetchall()

    adjacency: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        from_town_id = row["from_town_id"]
        to_town_id = row["to_town_id"]
        adjacency[from_town_id].append(_directed_edge(row, from_town_id, to_town_id))
        adjacency[to_town_id].append(_directed_edge(row, to_town_id, from_town_id))

    best: dict[int, tuple[float, int]] = {source_town_id: (0.0, 0)}
    previous: dict[int, tuple[int, dict]] = {}
    heap: list[tuple[float, int, int]] = [(0.0, 0, source_town_id)]

    while heap:
        distance, penalty, town_id = heapq.heappop(heap)
        if (distance, penalty) != best.get(town_id):
            continue
        if town_id == target_town_id:
            break

        for edge in adjacency.get(town_id, []):
            next_id = edge["to_town_id"]
            next_distance = distance + edge["distance_km"]
            next_penalty = penalty + _route_type_penalty(edge["route_type"])
            next_best = (next_distance, next_penalty)
            if next_best < best.get(next_id, (float("inf"), 10**9)):
                best[next_id] = next_best
                previous[next_id] = (town_id, edge)
                heapq.heappush(heap, (next_distance, next_penalty, next_id))

    if target_town_id not in best:
        return float("inf"), []

    path: list[dict] = []
    current_id = target_town_id
    while current_id != source_town_id:
        previous_id, edge = previous[current_id]
        path.append(edge)
        current_id = previous_id
    path.reverse()
    return best[target_town_id][0], path


def _towns_by_id(conn: sqlite3.Connection, town_ids: Iterable[int]) -> dict[int, dict]:
    unique_ids = list(dict.fromkeys(town_ids))
    if not unique_ids:
        return {}
    placeholders = ",".join("?" for _ in unique_ids)
    rows = conn.execute(
        f"SELECT * FROM towns WHERE id IN ({placeholders})",
        unique_ids,
    ).fetchall()
    return {row["id"]: _town_reference(row) for row in rows}


def _transport_action(route_type: str) -> str:
    return {
        "airway": "Fly",
        "railway": "Take the railway",
        "freeway": "Drive on the freeway",
        "bridge": "Cross by bridge road",
        "road": "Drive",
    }.get(route_type, "Travel")


def _transport_category(route_type: str) -> str:
    return "road_network" if route_type in ROAD_NETWORK_TYPES else route_type


def _format_stop_names(stops: list[dict]) -> str:
    return ", ".join(stop["name"] for stop in stops)


def _build_leg_instruction(category: str, from_town: dict, to_town: dict, stopovers: list[dict]) -> str:
    if category == "airway":
        base = f"Fly from {from_town['name']} to {to_town['name']}"
        return f"{base} with stopover(s) at {_format_stop_names(stopovers)}." if stopovers else f"{base}."
    if category == "railway":
        base = f"Take the railway from {from_town['name']} to {to_town['name']}"
        return f"{base} stopping at {_format_stop_names(stopovers)}." if stopovers else f"{base}."

    base = f"Drive from {from_town['name']} to {to_town['name']}"
    return f"{base} via {_format_stop_names(stopovers)}." if stopovers else f"{base}."


def _build_steps_and_legs(path: list[dict], town_lookup: dict[int, dict]) -> tuple[list[dict], list[dict]]:
    steps = []
    step_metrics = []
    for index, edge in enumerate(path, start=1):
        from_town = town_lookup[edge["from_town_id"]]
        to_town = town_lookup[edge["to_town_id"]]
        action = _transport_action(edge["route_type"])
        duration_hours = _edge_duration_hours(edge)
        cost_details = _edge_cost_details(edge, town_lookup)
        transport_cost = cost_details["amount"]
        step_metrics.append(
            {
                "duration_hours": duration_hours,
                "transport_cost": transport_cost,
            }
        )
        steps.append(
            {
                "step_number": index,
                "route_id": edge["route_id"],
                "edge_id": edge["edge_id"],
                "route_type": edge["route_type"],
                "transport_category": _transport_category(edge["route_type"]),
                "from": from_town,
                "to": to_town,
                "distance_km": _round_distance(edge["distance_km"]),
                "speed_limit_kmh": _speed_limit_kmh(edge["route_type"]),
                "duration_hours": _round_duration(duration_hours),
                "duration_minutes": _round_duration(duration_hours * 60),
                "formatted_duration": _format_duration(duration_hours),
                "cost": _round_money(transport_cost),
                "formatted_cost": _format_money(transport_cost),
                "cost_components": cost_details["components"],
                "toll_cost": _round_money(transport_cost),
                "formatted_toll_cost": _format_money(transport_cost),
                "toll_city_entry_fee_applied": cost_details["freeway_city_entry_fee_applied"],
                "railway_station_fee_applied": cost_details["railway_station_fee_applied"],
                "flight_departure_fee_applied": cost_details["flight_departure_fee_applied"],
                "is_bridge": edge["is_bridge"],
                "instruction": f"{action} from {from_town['name']} to {to_town['name']}.",
                "route_coords": edge["route_coords"],
                "screen_coords": edge["screen_coords"],
            }
        )

    legs = []
    current_edges: list[dict] = []
    current_category: str | None = None
    current_start_step = 1

    def flush_leg() -> None:
        if not current_edges or current_category is None:
            return
        stop_ids = [current_edges[0]["from_town_id"]]
        stop_ids.extend(edge["to_town_id"] for edge in current_edges)
        stops = [town_lookup[town_id] for town_id in stop_ids]
        stopovers = stops[1:-1]
        distance = sum(edge["distance_km"] for edge in current_edges)
        metric_slice = step_metrics[current_start_step - 1 : current_start_step - 1 + len(current_edges)]
        duration_hours = sum(metric["duration_hours"] for metric in metric_slice)
        transport_cost = sum(metric["transport_cost"] for metric in metric_slice)
        route_types = []
        for edge in current_edges:
            if edge["route_type"] not in route_types:
                route_types.append(edge["route_type"])
        from_town = stops[0]
        to_town = stops[-1]
        legs.append(
            {
                "leg_number": len(legs) + 1,
                "transport_category": current_category,
                "route_types": route_types,
                "from": from_town,
                "to": to_town,
                "distance_km": _round_distance(distance),
                "duration_hours": _round_duration(duration_hours),
                "duration_minutes": _round_duration(duration_hours * 60),
                "formatted_duration": _format_duration(duration_hours),
                "cost": _round_money(transport_cost),
                "formatted_cost": _format_money(transport_cost),
                "toll_cost": _round_money(transport_cost),
                "formatted_toll_cost": _format_money(transport_cost),
                "stops": stops,
                "stopovers": stopovers,
                "step_numbers": list(range(current_start_step, current_start_step + len(current_edges))),
                "instruction": _build_leg_instruction(
                    current_category,
                    from_town,
                    to_town,
                    stopovers,
                ),
            }
        )

    for step_index, edge in enumerate(path, start=1):
        category = _transport_category(edge["route_type"])
        if current_edges and category != current_category:
            flush_leg()
            current_edges = []
            current_start_step = step_index
        current_category = category
        current_edges.append(edge)
    flush_leg()

    return steps, legs


def _distance_breakdown(path: list[dict]) -> dict[str, float]:
    totals = {route_type: 0.0 for route_type in TRANSPORT_LAYERS}
    totals["road_network"] = 0.0
    for edge in path:
        route_type = edge["route_type"]
        totals[route_type] = totals.get(route_type, 0.0) + edge["distance_km"]
        if route_type in ROAD_NETWORK_TYPES:
            totals["road_network"] += edge["distance_km"]
    return {
        route_type: _round_distance(distance)
        for route_type, distance in totals.items()
        if distance > 0
    }


def _duration_breakdown(path: list[dict]) -> dict[str, dict]:
    totals = {route_type: 0.0 for route_type in TRANSPORT_LAYERS}
    totals["road_network"] = 0.0
    for edge in path:
        route_type = edge["route_type"]
        duration_hours = _edge_duration_hours(edge)
        totals[route_type] = totals.get(route_type, 0.0) + duration_hours
        if route_type in ROAD_NETWORK_TYPES:
            totals["road_network"] += duration_hours
    return {
        route_type: {
            "hours": _round_duration(duration),
            "minutes": _round_duration(duration * 60),
            "formatted": _format_duration(duration),
        }
        for route_type, duration in totals.items()
        if duration > 0
    }


def _total_duration_hours(path: list[dict]) -> float:
    return sum(_edge_duration_hours(edge) for edge in path)


def _cost_breakdown(path: list[dict], town_lookup: dict[int, dict]) -> dict[str, float]:
    totals = {route_type: 0.0 for route_type in TRANSPORT_LAYERS}
    totals["road_network"] = 0.0
    for edge in path:
        route_type = edge["route_type"]
        cost = _edge_transport_cost(edge, town_lookup)
        totals[route_type] = totals.get(route_type, 0.0) + cost
        if route_type in ROAD_NETWORK_TYPES:
            totals["road_network"] += cost
    return {
        route_type: _round_money(cost)
        for route_type, cost in totals.items()
        if cost > 0
    }


def _total_transport_cost(path: list[dict], town_lookup: dict[int, dict]) -> float:
    return sum(_edge_transport_cost(edge, town_lookup) for edge in path)


def _rows_to_count_map(rows: Iterable[sqlite3.Row]) -> dict[str, int]:
    return {row[0]: row[1] for row in rows}


@lru_cache(maxsize=1)
def _display_oriented_world_render() -> bytes:
    if not WORLD_RENDER_PATH.exists():
        raise HTTPException(status_code=404, detail="World render not found.")

    image_buffer = BytesIO()
    with Image.open(WORLD_RENDER_PATH) as image:
        image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(
            image_buffer,
            format="PNG",
        )
    return image_buffer.getvalue()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/map")
def get_map() -> dict:
    with _connect() as conn:
        terrain_counts = _rows_to_count_map(
            conn.execute(
                """
                SELECT COALESCE(terrain, 'unknown') AS label, COUNT(*)
                FROM towns
                GROUP BY COALESCE(terrain, 'unknown')
                ORDER BY label
                """
            )
        )
        size_counts = _rows_to_count_map(
            conn.execute(
                """
                SELECT size, COUNT(*)
                FROM towns
                GROUP BY size
                ORDER BY size
                """
            )
        )
        transport_counts = _rows_to_count_map(
            conn.execute(
                """
                SELECT route_type, COUNT(*)
                FROM transport_routes
                GROUP BY route_type
                ORDER BY route_type
                """
            )
        )
        summary = conn.execute(
            """
            SELECT
                COUNT(*) AS town_count,
                COALESCE(SUM(population), 0) AS total_population,
                MIN(x_coordinate) AS min_x,
                MAX(x_coordinate) AS max_x,
                MIN(y_coordinate) AS min_y,
                MAX(y_coordinate) AS max_y
            FROM towns
            """
        ).fetchone()

    return {
        "width": MAP_WIDTH,
        "height": MAP_HEIGHT,
        "bounds": {
            "min_x": summary["min_x"],
            "max_x": summary["max_x"],
            "min_y": summary["min_y"],
            "max_y": summary["max_y"],
        },
        "images": {
            "terrain": "/assets/world-render.png?orientation=display-v2",
            "town_footprints": "/assets/town-footprints.png",
            "transport_overlays": {
                layer: f"/assets/transport/{layer}.png"
                for layer in TRANSPORT_LAYERS
            },
        },
        "summary": {
            "town_count": summary["town_count"],
            "total_population": summary["total_population"],
            "formatted_total_population": _format_number(summary["total_population"]),
            "terrain_counts": terrain_counts,
            "size_counts": size_counts,
            "transport_counts": transport_counts,
        },
    }


@app.get("/api/towns")
def get_towns(
    search: str | None = Query(default=None),
    limit: int = Query(default=2000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    where = ""
    params: list[object] = []
    if search:
        where = """
            WHERE LOWER(name) LIKE ?
                OR LOWER(size) LIKE ?
                OR LOWER(COALESCE(specialization, '')) LIKE ?
                OR LOWER(COALESCE(terrain, '')) LIKE ?
        """
        token = f"%{search.lower()}%"
        params.extend([token, token, token, token])

    with _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM towns {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT *
            FROM towns
            {where}
            ORDER BY population DESC, name
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "towns": [_town_from_row(row) for row in rows],
    }


@app.get("/api/towns/{town_id}")
def get_town(town_id: int) -> dict:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM towns WHERE id = ?", (town_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Town not found.")
    return _town_from_row(row)


@app.get("/api/transport-routes")
def get_transport_routes(types: str | None = Query(default=None)) -> dict:
    requested_layers = TRANSPORT_LAYERS
    params: list[object] = []
    where = ""

    if types:
        parsed = tuple(layer.strip() for layer in types.split(",") if layer.strip())
        unknown = sorted(set(parsed) - set(TRANSPORT_LAYERS))
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown transport layer(s): {', '.join(unknown)}",
            )
        requested_layers = parsed

    if requested_layers:
        placeholders = ",".join("?" for _ in requested_layers)
        where = f"WHERE tr.route_type IN ({placeholders})"
        params.extend(requested_layers)

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                tr.*,
                from_town.name AS from_town_name,
                to_town.name AS to_town_name
            FROM transport_routes AS tr
            JOIN towns AS from_town ON from_town.id = tr.from_town_id
            JOIN towns AS to_town ON to_town.id = tr.to_town_id
            {where}
            ORDER BY tr.route_type, tr.edge_id
            """,
            params,
        ).fetchall()

    return {
        "total": len(rows),
        "routes": [_route_from_row(row) for row in rows],
    }


@app.get("/api/directions")
def get_directions(
    origin: str = Query(alias="from", min_length=1),
    destination: str = Query(alias="to", min_length=1),
    transports: str | None = Query(
        default=None,
        description=(
            "Comma-separated route types to use. Valid values: road, bridge, "
            "freeway, railway, airway, road_network, train, flight. Defaults to all."
        ),
    ),
    types: str | None = Query(
        default=None,
        description="Alias for transports.",
    ),
) -> dict:
    requested_route_types = _parse_route_types(transports or types)

    with _connect() as conn:
        source = _resolve_town(conn, origin, "Origin")
        target = _resolve_town(conn, destination, "Destination")
        total_distance, path = _shortest_transport_path(
            conn,
            source["id"],
            target["id"],
            requested_route_types,
        )
        if total_distance == float("inf"):
            raise HTTPException(
                status_code=404,
                detail=(
                    "No route found between the requested locations using "
                    f"transport type(s): {', '.join(requested_route_types)}."
                ),
            )

        path_town_ids = [source["id"]]
        path_town_ids.extend(edge["to_town_id"] for edge in path)
        town_lookup = _towns_by_id(conn, path_town_ids)

    steps, legs = _build_steps_and_legs(path, town_lookup)
    total_duration_hours = _total_duration_hours(path)
    total_transport_cost = _total_transport_cost(path, town_lookup)
    return {
        "origin": _town_reference(source),
        "destination": _town_reference(target),
        "requested_transport_types": requested_route_types,
        "algorithm": "dijkstra_shortest_path_by_distance_km",
        "routing_config": {
            "speed_limits_kmh": TRANSPORT_ROUTING["speed_limits_kmh"],
            "costs": TRANSPORT_ROUTING["costs"],
        },
        "total_distance_km": _round_distance(total_distance),
        "distance_by_transport_km": _distance_breakdown(path),
        "eta": {
            "hours": _round_duration(total_duration_hours),
            "minutes": _round_duration(total_duration_hours * 60),
            "formatted": _format_duration(total_duration_hours),
        },
        "duration_by_transport": _duration_breakdown(path),
        "cost": _round_money(total_transport_cost),
        "formatted_cost": _format_money(total_transport_cost),
        "cost_by_transport": _cost_breakdown(path, town_lookup),
        "toll_cost": _round_money(total_transport_cost),
        "formatted_toll_cost": _format_money(total_transport_cost),
        "town_path": [town_lookup[town_id] for town_id in path_town_ids],
        "leg_count": len(legs),
        "step_count": len(steps),
        "legs": legs,
        "steps": steps,
    }


@app.get("/assets/world-render.png")
def world_render() -> Response:
    return Response(
        content=_display_oriented_world_render(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/assets/town-footprints.png")
def town_footprints() -> Response:
    if not TOWN_MAP_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="Town map HTML not found.")

    html = TOWN_MAP_HTML_PATH.read_text(encoding="utf-8")
    match = re.search(
        r'"footprint_image_uri":\s*"data:image/png;base64,([^"]+)"',
        html,
    )
    if not match:
        raise HTTPException(status_code=404, detail="Town footprint image not found.")

    image_bytes = base64.b64decode(match.group(1))
    return Response(content=image_bytes, media_type="image/png")


@app.get("/assets/transport/{layer}.png")
def transport_overlay(layer: str) -> FileResponse:
    if layer not in TRANSPORT_LAYERS:
        raise HTTPException(status_code=404, detail="Transport layer not found.")
    path = TRANSPORT_OVERLAY_DIR / f"transport_overlay_{layer}s.png"
    if layer == "bridge":
        path = TRANSPORT_OVERLAY_DIR / "transport_overlay_bridges.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Transport overlay not found.")
    return FileResponse(path, media_type="image/png")
