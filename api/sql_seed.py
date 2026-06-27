from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = BASE_DIR / "api" / "database.db"
DEFAULT_TOWN_CSV_PATH = BASE_DIR / "csv" / "town_data.csv"
DEFAULT_TRANSPORT_CSV_PATH = BASE_DIR / "csv" / "transport_routes.csv"


def _none_if_empty(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value != "" else None


def _int_or_none(value):
    value = _none_if_empty(value)
    return int(value) if value is not None else None


def _float_or_none(value):
    value = _none_if_empty(value)
    return float(value) if value is not None else None


def _bool_to_int(value):
    value = _none_if_empty(value)
    if value is None:
        return 0
    return 1 if value.lower() in ("1", "true", "yes", "y") else 0


def _create_schema(conn):
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DROP TABLE IF EXISTS transport_routes")
    conn.execute("DROP TABLE IF EXISTS towns")
    conn.execute(
        """
        CREATE TABLE towns (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            size TEXT NOT NULL,
            specialization TEXT,
            population INTEGER NOT NULL,
            density REAL NOT NULL,
            area_sq_km REAL NOT NULL,
            radius_km REAL NOT NULL,
            target_area_pixels INTEGER NOT NULL,
            placed_area_pixels INTEGER NOT NULL,
            established_year INTEGER NOT NULL,
            abandoned_year INTEGER,
            terrain TEXT,
            x_coordinate REAL NOT NULL,
            y_coordinate REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE transport_routes (
            route_id TEXT PRIMARY KEY,
            route_type TEXT NOT NULL,
            edge_id INTEGER NOT NULL,
            from_town_id INTEGER NOT NULL,
            to_town_id INTEGER NOT NULL,
            distance_km REAL NOT NULL,
            is_bridge INTEGER NOT NULL DEFAULT 0,
            route_coords_json TEXT NOT NULL,
            screen_coords_json TEXT NOT NULL,
            FOREIGN KEY (from_town_id) REFERENCES towns(id),
            FOREIGN KEY (to_town_id) REFERENCES towns(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_transport_routes_type ON transport_routes(route_type)"
    )
    conn.execute(
        "CREATE INDEX idx_transport_routes_from_town ON transport_routes(from_town_id)"
    )
    conn.execute(
        "CREATE INDEX idx_transport_routes_to_town ON transport_routes(to_town_id)"
    )


def _load_towns(conn, town_csv_path):
    with open(town_csv_path, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for fallback_id, row in enumerate(reader):
            town_id = row.get("Town ID", fallback_id)
            conn.execute(
                """
                INSERT INTO towns (
                    id,
                    name,
                    size,
                    specialization,
                    population,
                    density,
                    area_sq_km,
                    radius_km,
                    target_area_pixels,
                    placed_area_pixels,
                    established_year,
                    abandoned_year,
                    terrain,
                    x_coordinate,
                    y_coordinate
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(town_id),
                    row["Name"],
                    row["Size"],
                    _none_if_empty(row["Specialization"]),
                    _int_or_none(row["Population"]),
                    _float_or_none(row["Density"]),
                    _float_or_none(row["Area (sq km)"]),
                    _float_or_none(row["Radius (km)"]),
                    _int_or_none(row["Target Area Pixels"]),
                    _int_or_none(row["Placed Area Pixels"]),
                    _int_or_none(row["Established Year"]),
                    _int_or_none(row["Abandoned Year"]),
                    _none_if_empty(row["Terrain"]),
                    _float_or_none(row["X Coordinate"]),
                    _float_or_none(row["Y Coordinate"]),
                ),
            )


def _load_transport_routes(conn, transport_csv_path):
    if not transport_csv_path.exists():
        return 0

    route_count = 0
    with open(transport_csv_path, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            conn.execute(
                """
                INSERT INTO transport_routes (
                    route_id,
                    route_type,
                    edge_id,
                    from_town_id,
                    to_town_id,
                    distance_km,
                    is_bridge,
                    route_coords_json,
                    screen_coords_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["route_id"],
                    row["route_type"],
                    _int_or_none(row["edge_id"]),
                    _int_or_none(row["from_town_id"]),
                    _int_or_none(row["to_town_id"]),
                    _float_or_none(row["distance_km"]),
                    _bool_to_int(row["is_bridge"]),
                    row["route_coords_json"],
                    row["screen_coords_json"],
                ),
            )
            route_count += 1
    return route_count


def seed_database(database_path, town_csv_path, transport_csv_path):
    database_path = Path(database_path)
    town_csv_path = Path(town_csv_path)
    transport_csv_path = Path(transport_csv_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_path) as conn:
        _create_schema(conn)
        _load_towns(conn, town_csv_path)
        route_count = _load_transport_routes(conn, transport_csv_path)
        town_count = conn.execute("SELECT COUNT(*) FROM towns").fetchone()[0]
        conn.commit()

    return town_count, route_count


def parse_args():
    parser = argparse.ArgumentParser(description="Seed the PyTown SQLite database.")
    parser.add_argument("--database", default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--town-csv", default=DEFAULT_TOWN_CSV_PATH)
    parser.add_argument("--transport-csv", default=DEFAULT_TRANSPORT_CSV_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    town_count, route_count = seed_database(
        args.database,
        args.town_csv,
        args.transport_csv,
    )
    print(f"Seeded {town_count} towns")
    print(f"Seeded {route_count} transport routes")
    print(f"Wrote SQLite database to {args.database}")


if __name__ == "__main__":
    main()
