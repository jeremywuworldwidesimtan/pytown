from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from config import (
    GLOBAL_SEED,
    MAP,
    MAP_COLORS,
    MAP_CONTINENT,
    MAP_NOISE,
    MAP_TERRAIN,
)

try:
    from opensimplex import OpenSimplex
except ModuleNotFoundError:
    OpenSimplex = None

# Map size is stored as (width, height) in pixels/cells.
MAP_SIZE = MAP["size"]
MAP_SCALE = MAP["scale"]
NOISE_SETTINGS = MAP_NOISE
COLORS = MAP_COLORS
WATER_LEVEL = MAP_TERRAIN["water_level"]
BEACH_WIDTH = MAP_TERRAIN["beach_width"]
PLAINS_LEVEL = MAP_TERRAIN["plains_level"]
HILLS_LEVEL = MAP_TERRAIN["hills_level"]
MOUNTAINS_LEVEL = MAP_TERRAIN["mountains_level"]
CONTINENT_SETTINGS = MAP_CONTINENT


def classify_terrain_value(elevation, water_level=WATER_LEVEL, beach_width=BEACH_WIDTH):
    """Return the terrain band name for a normalized elevation value."""
    beach_level = min(water_level + beach_width, 1.0)
    if elevation < water_level:
        return "water"
    if elevation < beach_level:
        return "beach"
    if elevation < PLAINS_LEVEL:
        return "plains"
    if elevation < HILLS_LEVEL:
        return "hills"
    if elevation < MOUNTAINS_LEVEL:
        return "mountains"
    return "snow"


def town_center_terrain_mask(
    terrain,
    water_level=WATER_LEVEL,
    beach_width=BEACH_WIDTH,
):
    """Return a boolean mask for terrain pixels where town centers may spawn."""
    beach_level = min(water_level + beach_width, 1.0)
    beach_mask = (terrain >= water_level) & (terrain < beach_level)
    plains_mask = (terrain >= beach_level) & (terrain < PLAINS_LEVEL)
    hills_mask = (terrain >= PLAINS_LEVEL) & (terrain < HILLS_LEVEL)
    return beach_mask | plains_mask | hills_mask


def update_point(coords, seed):
    """Return the base OpenSimplex elevation at a single coordinate."""
    if OpenSimplex is None:
        raise ModuleNotFoundError("opensimplex is required to generate terrain")

    noise = OpenSimplex(seed=seed)
    return noise.noise2(coords[0] / MAP_SCALE, coords[1] / MAP_SCALE)


def normalize(input_map, min_val=None, max_val=None, exponent=1.0):
    min_val = float(np.min(input_map)) if min_val is None else float(min_val)
    max_val = float(np.max(input_map)) if max_val is None else float(max_val)
    scale = max_val - min_val
    if scale == 0:
        return np.zeros_like(input_map, dtype=np.float32)

    normalized = np.clip((input_map - min_val) / scale, 0.0, 1.0)
    return normalized.astype(np.float32) ** exponent


def _map_dimensions(map_size):
    width, height = map_size
    if width <= 0 or height <= 0:
        raise ValueError("map_size must contain positive width and height")
    return int(width), int(height)


def _row_chunks(height, chunk_rows):
    if chunk_rows is None or chunk_rows <= 0:
        chunk_rows = height

    for start_y in range(0, height, int(chunk_rows)):
        yield start_y, min(start_y + int(chunk_rows), height)


def _resize_bilinear(source, target_shape):
    target_height, target_width = target_shape
    source_height, source_width = source.shape
    if source.shape == target_shape:
        return source.astype(np.float32, copy=False)

    x = np.linspace(0, source_width - 1, target_width, dtype=np.float32)
    y = np.linspace(0, source_height - 1, target_height, dtype=np.float32)

    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = np.clip(x0 + 1, 0, source_width - 1)
    y1 = np.clip(y0 + 1, 0, source_height - 1)

    x_weight = (x - x0)[None, :]
    y_weight = (y - y0)[:, None]

    top = source[y0[:, None], x0] * (1.0 - x_weight) + source[y0[:, None], x1] * x_weight
    bottom = source[y1[:, None], x0] * (1.0 - x_weight) + source[y1[:, None], x1] * x_weight
    return (top * (1.0 - y_weight) + bottom * y_weight).astype(np.float32)


def _smoothstep(edge0, edge1, values):
    if edge0 == edge1:
        return np.where(values >= edge1, 1.0, 0.0).astype(np.float32)

    t = np.clip((values - edge0) / (edge1 - edge0), 0.0, 1.0)
    return (t * t * (3.0 - (2.0 * t))).astype(np.float32)


def _continent_falloff(
    map_size,
    seed=GLOBAL_SEED,
    coast_start=CONTINENT_SETTINGS["coast_start"],
    coast_end=CONTINENT_SETTINGS["coast_end"],
    edge_power=CONTINENT_SETTINGS["edge_power"],
    coast_roughness=CONTINENT_SETTINGS["coast_roughness"],
    coast_noise_scale=CONTINENT_SETTINGS["coast_noise_scale"],
    coast_noise_octaves=CONTINENT_SETTINGS["coast_noise_octaves"],
    chunk_rows=MAP["chunk_rows"],
    sample_step=MAP["sample_step"],
):
    width, height = _map_dimensions(map_size)
    x = np.linspace(-1.0, 1.0, width, dtype=np.float32)
    y = np.linspace(-1.0, 1.0, height, dtype=np.float32)

    distance_from_center = (
        np.abs(x)[None, :] ** edge_power + np.abs(y)[:, None] ** edge_power
    ) ** (1.0 / edge_power)
    if coast_roughness > 0:
        coast_noise = _fractal_noise_2d(
            seed=seed + 104_729,
            map_size=map_size,
            scale=coast_noise_scale,
            octaves=coast_noise_octaves,
            persistence=CONTINENT_SETTINGS["coast_noise_persistence"],
            lacunarity=CONTINENT_SETTINGS["coast_noise_lacunarity"],
            chunk_rows=chunk_rows,
            sample_step=max(
                sample_step * CONTINENT_SETTINGS["coast_noise_sample_step_multiplier"],
                CONTINENT_SETTINGS["coast_noise_min_sample_step"],
            ),
        )
        coast_noise = (normalize(coast_noise) * 2.0) - 1.0
        inner_band = _smoothstep(
            coast_start + CONTINENT_SETTINGS["coast_inner_start_offset"],
            coast_start + CONTINENT_SETTINGS["coast_inner_end_offset"],
            distance_from_center,
        )
        outer_band = 1.0 - _smoothstep(
            coast_end + CONTINENT_SETTINGS["coast_outer_start_offset"],
            coast_end,
            distance_from_center,
        )
        coast_band = inner_band * outer_band
        distance_from_center = distance_from_center + (
            coast_noise * coast_roughness * coast_band
        )

    return 1.0 - _smoothstep(coast_start, coast_end, distance_from_center)


def _fractal_noise_2d(
    seed,
    map_size=MAP_SIZE,
    scale=MAP_SCALE,
    octaves=NOISE_SETTINGS["octaves"],
    persistence=NOISE_SETTINGS["persistence"],
    lacunarity=NOISE_SETTINGS["lacunarity"],
    chunk_rows=MAP["chunk_rows"],
    sample_step=MAP["sample_step"],
):
    """Generate chunked fractal OpenSimplex noise as a float32 heightmap."""
    width, height = _map_dimensions(map_size)
    if scale <= 0:
        raise ValueError("scale must be positive")
    if octaves <= 0:
        raise ValueError("octaves must be positive")
    if sample_step <= 0:
        raise ValueError("sample_step must be positive")
    if OpenSimplex is None:
        raise ModuleNotFoundError("opensimplex is required to generate terrain")

    simplex = OpenSimplex(seed=int(seed))
    sample_width = max(2, int(np.ceil(width / sample_step)) + 1)
    sample_height = max(2, int(np.ceil(height / sample_step)) + 1)
    x_coords = np.linspace(0, (width - 1) / float(scale), sample_width, dtype=np.float64)
    y_coords = np.linspace(0, (height - 1) / float(scale), sample_height, dtype=np.float64)
    sampled_heightmap = np.zeros((sample_height, sample_width), dtype=np.float32)

    amplitude = 1.0
    frequency = 1.0
    amplitude_sum = 0.0

    for _ in range(int(octaves)):
        x_octave = x_coords * frequency
        for start_y, end_y in _row_chunks(sample_height, chunk_rows):
            y_octave = y_coords[start_y:end_y] * frequency
            sampled_heightmap[start_y:end_y] += (
                simplex.noise2array(x_octave, y_octave).astype(np.float32) * amplitude
            )

        amplitude_sum += amplitude
        amplitude *= persistence
        frequency *= lacunarity

    sampled_heightmap /= amplitude_sum
    return _resize_bilinear(sampled_heightmap, (height, width))


def _shape_as_continent(
    heightmap,
    map_size,
    seed=GLOBAL_SEED,
    water_level=WATER_LEVEL,
    exponent=1.0,
    coast_start=CONTINENT_SETTINGS["coast_start"],
    coast_end=CONTINENT_SETTINGS["coast_end"],
    edge_power=CONTINENT_SETTINGS["edge_power"],
    land_floor_above_water=CONTINENT_SETTINGS["land_floor_above_water"],
    coast_roughness=CONTINENT_SETTINGS["coast_roughness"],
    coast_noise_scale=CONTINENT_SETTINGS["coast_noise_scale"],
    coast_noise_octaves=CONTINENT_SETTINGS["coast_noise_octaves"],
    chunk_rows=MAP["chunk_rows"],
    sample_step=MAP["sample_step"],
):
    terrain = normalize(heightmap, exponent=exponent)
    falloff = _continent_falloff(
        map_size,
        seed=seed,
        coast_start=coast_start,
        coast_end=coast_end,
        edge_power=edge_power,
        coast_roughness=coast_roughness,
        coast_noise_scale=coast_noise_scale,
        coast_noise_octaves=coast_noise_octaves,
        chunk_rows=chunk_rows,
        sample_step=sample_step,
    )

    land_floor = np.clip(water_level + land_floor_above_water, 0.0, 0.95)
    terrain = land_floor + (terrain * (1.0 - land_floor))
    return np.clip(terrain * falloff, 0.0, 1.0).astype(np.float32)


def generate_terrain(
    seed=GLOBAL_SEED,
    exponent=MAP["exponent"],
    parallel=False,
    workers=None,
    chunk_rows=MAP["chunk_rows"],
    map_size=MAP_SIZE,
    scale=MAP_SCALE,
    octaves=NOISE_SETTINGS["octaves"],
    persistence=NOISE_SETTINGS["persistence"],
    lacunarity=NOISE_SETTINGS["lacunarity"],
    sample_step=MAP["sample_step"],
    water_level=WATER_LEVEL,
    coast_start=CONTINENT_SETTINGS["coast_start"],
    coast_end=CONTINENT_SETTINGS["coast_end"],
    edge_power=CONTINENT_SETTINGS["edge_power"],
    land_floor_above_water=CONTINENT_SETTINGS["land_floor_above_water"],
    coast_roughness=CONTINENT_SETTINGS["coast_roughness"],
    coast_noise_scale=CONTINENT_SETTINGS["coast_noise_scale"],
    coast_noise_octaves=CONTINENT_SETTINGS["coast_noise_octaves"],
):
    """Generate normalized 2D terrain using vectorized OpenSimplex noise.

    ``parallel`` and ``workers`` are accepted for compatibility with the older
    implementation. OpenSimplex's array API is already vectorized, so chunking
    with ``chunk_rows`` is usually faster and more memory-friendly than process
    pools for this workload.

    ``sample_step`` controls the speed/detail tradeoff. The default samples one
    OpenSimplex value for every 4 output cells and interpolates between them.
    Use 1 for full-resolution noise, or a larger value for faster, smoother maps.

    ``water_level`` and ``land_floor_above_water`` control lake frequency. The
    continent falloff forces all map edges below sea level while keeping most
    inland lowlands above sea level.

    ``coast_roughness`` controls how strongly the coastline is warped by
    low-frequency noise. Use 0 for a smooth superellipse continent.
    """
    _ = parallel, workers

    base = _fractal_noise_2d(
        seed=seed,
        map_size=map_size,
        scale=scale,
        octaves=octaves,
        persistence=persistence,
        lacunarity=lacunarity,
        chunk_rows=chunk_rows,
        sample_step=sample_step,
    )
    ridges = 1.0 - np.abs(base)
    heightmap = (
        base * MAP["base_height_weight"]
    ) + (
        ridges * MAP["ridge_height_weight"]
    )
    return _shape_as_continent(
        heightmap,
        map_size=map_size,
        seed=seed,
        water_level=water_level,
        exponent=exponent,
        coast_start=coast_start,
        coast_end=coast_end,
        edge_power=edge_power,
        land_floor_above_water=land_floor_above_water,
        coast_roughness=coast_roughness,
        coast_noise_scale=coast_noise_scale,
        coast_noise_octaves=coast_noise_octaves,
        chunk_rows=chunk_rows,
        sample_step=sample_step,
    )


def render_terrain(terrain, water_level=WATER_LEVEL, beach_width=BEACH_WIDTH):
    color_map = np.empty(terrain.shape + (3,), dtype=np.uint8)
    beach_level = min(water_level + beach_width, 1.0)
    water_mask = terrain < water_level
    beach_mask = (terrain >= water_level) & (terrain < beach_level)
    plains_mask = (terrain >= beach_level) & (terrain < PLAINS_LEVEL)
    hills_mask = (terrain >= PLAINS_LEVEL) & (terrain < HILLS_LEVEL)
    mountains_mask = (terrain >= HILLS_LEVEL) & (terrain < MOUNTAINS_LEVEL)
    snow_mask = terrain >= MOUNTAINS_LEVEL

    color_map[water_mask] = COLORS["water"]
    color_map[beach_mask] = COLORS["beach"]
    color_map[plains_mask] = COLORS["plains"]
    color_map[hills_mask] = COLORS["hills"]
    color_map[mountains_mask] = COLORS["mountains"]
    color_map[snow_mask] = COLORS["snow"]
    return color_map


def export_heightmap(heightmap, filename):
    """Export a normalized heightmap as .npy, .csv, or grayscale .png."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()

    if suffix == ".npy":
        np.save(path, heightmap.astype(np.float32, copy=False))
    elif suffix == ".csv":
        np.savetxt(path, heightmap, delimiter=",", fmt="%.6f")
    elif suffix == ".png":
        plt.imsave(path, heightmap, cmap="gray", vmin=0.0, vmax=1.0)
    else:
        raise ValueError("heightmap export filename must end with .npy, .csv, or .png")

    return path


def load_heightmap(filename):
    """Load a numeric heightmap exported as .npy or .csv."""
    path = Path(filename)
    suffix = path.suffix.lower()

    if suffix == ".npy":
        return np.load(path).astype(np.float32, copy=False)
    if suffix == ".csv":
        return np.loadtxt(path, delimiter=",", dtype=np.float32)

    raise ValueError("heightmap import filename must end with .npy or .csv")


def _parse_args():
    parser = argparse.ArgumentParser(description="Generate and export terrain maps.")
    parser.add_argument("--seed", type=int, default=GLOBAL_SEED)
    parser.add_argument("--width", type=int, default=MAP_SIZE[0])
    parser.add_argument("--height", type=int, default=MAP_SIZE[1])
    parser.add_argument("--sample-step", type=int, default=MAP["sample_step"])
    parser.add_argument("--water-level", type=float, default=WATER_LEVEL)
    parser.add_argument(
        "--coast-roughness",
        type=float,
        default=CONTINENT_SETTINGS["coast_roughness"],
    )
    parser.add_argument("--export-heightmap")
    parser.add_argument("--export-render")
    parser.add_argument("--no-show", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    terrain = generate_terrain(
        seed=args.seed,
        map_size=(args.width, args.height),
        sample_step=args.sample_step,
        water_level=args.water_level,
        coast_roughness=args.coast_roughness,
    )
    color_map = render_terrain(terrain, water_level=args.water_level)

    if args.export_heightmap:
        heightmap_path = export_heightmap(terrain, args.export_heightmap)
        print(f"Exported heightmap to {heightmap_path}")

    if args.export_render:
        render_path = Path(args.export_render)
        render_path.parent.mkdir(parents=True, exist_ok=True)
        plt.imsave(render_path, color_map)
        print(f"Exported rendered map to {render_path}")

    if not args.no_show:
        plt.imshow(color_map)
        plt.title("Generated Terrain Heightmap")
        plt.xlabel("X Coordinate")
        plt.ylabel("Y Coordinate")
        plt.show()
