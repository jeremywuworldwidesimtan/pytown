from __future__ import annotations

import base64
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


BASE_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = BASE_DIR / "api" / "database.db"
WORLD_RENDER_PATH = BASE_DIR / "csv" / "world_render.png"
TOWN_MAP_HTML_PATH = BASE_DIR / "web" / "town_map.html"
TRANSPORT_OVERLAY_DIR = BASE_DIR / "web"

MAP_WIDTH = 4096
MAP_HEIGHT = 4096
TRANSPORT_LAYERS = ("road", "bridge", "freeway", "railway", "airway")


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
