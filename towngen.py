from datetime import datetime
import heapq
from pathlib import Path
import math
import random

import numpy as np

from config import (
    CITY_SPECIALIZATIONS as CONFIG_CITY_SPECIALIZATIONS,
    GLOBAL_SEED,
    MAP,
    TOWN_DENSITY,
    TOWN_GENERATION,
    TOWN_NAME_GENERATOR,
    TOWN_PLACEMENT,
    TOWN_SIZES,
)
import townnamegen
from mapgen import (
    BEACH_WIDTH,
    HILLS_LEVEL,
    MOUNTAINS_LEVEL,
    PLAINS_LEVEL,
    WATER_LEVEL,
    classify_terrain_value,
    load_heightmap,
    render_terrain,
    town_center_terrain_mask,
)

random.seed(GLOBAL_SEED)  # Set a fixed seed for reproducibility

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_HEIGHTMAP_PATH = BASE_DIR / "csv" / "world_heightmap.npy"

MAP_WIDTH, MAP_LENGTH = MAP["size"]  # Dimensions in km; one pixel is one sq km.
_GROWTH_NEIGHBORS = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)

town_sizes = TOWN_SIZES
town_density = TOWN_DENSITY
CITY_SPECIALIZATIONS = CONFIG_CITY_SPECIALIZATIONS

townNameGen = townnamegen.TownNameGenerator(**TOWN_NAME_GENERATOR)


class TownPlacementMap:
    """Adapts a mapgen heightmap to centered kilometer town coordinates."""

    def __init__(
        self,
        heightmap,
        water_level=WATER_LEVEL,
        beach_width=BEACH_WIDTH,
    ):
        if heightmap.ndim != 2:
            raise ValueError("heightmap must be a 2D array")

        self.heightmap = heightmap
        self.height, self.width = heightmap.shape
        self.water_level = water_level
        self.beach_width = beach_width
        self.townable_mask = town_center_terrain_mask(
            self.heightmap,
            water_level=self.water_level,
            beach_width=self.beach_width,
        )
        beach_level = min(self.water_level + self.beach_width, 1.0)
        self.water_mask = self.heightmap < self.water_level
        self.beach_mask = (
            (self.heightmap >= self.water_level) & (self.heightmap < beach_level)
        )
        self.hills_mask = (
            (self.heightmap >= PLAINS_LEVEL) & (self.heightmap < HILLS_LEVEL)
        )
        self.plains_mask = (
            (self.heightmap >= beach_level) & (self.heightmap < PLAINS_LEVEL)
        )
        self.mountains_mask = (
            (self.heightmap >= HILLS_LEVEL) & (self.heightmap < MOUNTAINS_LEVEL)
        )
        self.snow_mask = self.heightmap >= MOUNTAINS_LEVEL
        self.mining_outpost_mask = self.mountains_mask | self.snow_mask
        self.industrial_outpost_mask = self.plains_mask | self.hills_mask
        self.hamlet_outpost_mask = self.mining_outpost_mask | self.industrial_outpost_mask
        self.coastal_townable_mask = self.beach_mask & self.townable_mask
        self.occupied_mask = np.zeros((self.height, self.width), dtype=bool)
        self.valid_pixel_indices = np.flatnonzero(self.townable_mask)
        self.coastal_pixel_indices = np.flatnonzero(self.coastal_townable_mask)
        self.mining_outpost_pixel_indices = np.flatnonzero(self.mining_outpost_mask)
        self.industrial_outpost_pixel_indices = np.flatnonzero(
            self.industrial_outpost_mask
        )
        self.hamlet_outpost_pixel_indices = np.flatnonzero(self.hamlet_outpost_mask)

        if self.valid_pixel_indices.size == 0:
            raise ValueError("heightmap has no beach, plains, or hills town pixels")
        if self.hamlet_outpost_pixel_indices.size == 0:
            raise ValueError("heightmap has no hamlet/outpost placement pixels")

    @classmethod
    def from_file(
        cls,
        filename=DEFAULT_HEIGHTMAP_PATH,
        water_level=WATER_LEVEL,
        beach_width=BEACH_WIDTH,
    ):
        return cls(
            load_heightmap(filename),
            water_level=water_level,
            beach_width=beach_width,
        )

    def pixel_to_center_coords(self, pixel_x, pixel_y):
        loc_x = pixel_x + 0.5 - (self.width / 2)
        loc_y = pixel_y + 0.5 - (self.height / 2)
        return loc_x, loc_y

    def coords_to_pixel(self, loc_x, loc_y):
        pixel_x = math.floor(loc_x + (self.width / 2))
        pixel_y = math.floor(loc_y + (self.height / 2))
        pixel_x = min(max(pixel_x, 0), self.width - 1)
        pixel_y = min(max(pixel_y, 0), self.height - 1)
        return pixel_x, pixel_y

    def terrain_at_pixel(self, pixel_x, pixel_y):
        elevation = float(self.heightmap[pixel_y, pixel_x])
        return classify_terrain_value(
            elevation,
            water_level=self.water_level,
            beach_width=self.beach_width,
        )

    def terrain_at_coords(self, loc_x, loc_y):
        pixel_x, pixel_y = self.coords_to_pixel(loc_x, loc_y)
        return self.terrain_at_pixel(pixel_x, pixel_y)

    def is_townable_pixel(self, pixel_x, pixel_y):
        return (
            0 <= pixel_x < self.width
            and 0 <= pixel_y < self.height
            and self.townable_mask[pixel_y, pixel_x]
        )

    def is_available_pixel(self, pixel_x, pixel_y, allowed_mask):
        return (
            0 <= pixel_x < self.width
            and 0 <= pixel_y < self.height
            and allowed_mask[pixel_y, pixel_x]
            and not self.occupied_mask[pixel_y, pixel_x]
        )

    def is_available_town_pixel(self, pixel_x, pixel_y):
        return self.is_available_pixel(pixel_x, pixel_y, self.townable_mask)

    def _available_pixel_from_indices(self, pixel_indices, allowed_mask):
        if pixel_indices.size == 0:
            return None

        for _ in range(TOWN_PLACEMENT["candidate_sample_attempts"]):
            flat_index = int(pixel_indices[random.randrange(pixel_indices.size)])
            pixel_y, pixel_x = divmod(flat_index, self.width)
            if self.is_available_pixel(pixel_x, pixel_y, allowed_mask):
                return pixel_x, pixel_y

        available_pixels = np.flatnonzero(
            np.take(allowed_mask & ~self.occupied_mask, pixel_indices)
        )
        if available_pixels.size == 0:
            return None

        flat_index = int(pixel_indices[random.choice(available_pixels)])
        return divmod(flat_index, self.width)[::-1]

    def allowed_center_mask_for_size(self, town_size):
        if town_size == "Hamlet/Outpost":
            return self.hamlet_outpost_mask
        return self.townable_mask

    def allowed_footprint_mask_for_town(self, town):
        if town.size == "Hamlet/Outpost":
            if town.terrain in ("mountains", "snow"):
                return self.mining_outpost_mask
            return self.industrial_outpost_mask
        return self.townable_mask

    def random_town_center(self, town_size=None):
        if town_size == "Hamlet/Outpost":
            modes = [
                (self.mining_outpost_pixel_indices, self.mining_outpost_mask),
                (self.industrial_outpost_pixel_indices, self.industrial_outpost_mask),
            ]
            random.shuffle(modes)
            pixel = None
            for pixel_indices, allowed_mask in modes:
                pixel = self._available_pixel_from_indices(
                    pixel_indices,
                    allowed_mask,
                )
                if pixel is not None:
                    break

            if pixel is None:
                raise Exception("No available hamlet/outpost pixels remain.")

            pixel_x, pixel_y = pixel
            loc_x, loc_y = self.pixel_to_center_coords(pixel_x, pixel_y)
            return loc_x, loc_y, self.terrain_at_pixel(pixel_x, pixel_y)

        coastal_bias = {
            "Metropolis": TOWN_GENERATION["metropolis_coastal_bias"],
            "Megaopolis": TOWN_GENERATION["megaopolis_coastal_bias"],
        }.get(town_size, 0.0)

        pixel = None
        if coastal_bias > 0 and random.random() < coastal_bias:
            pixel = self._available_pixel_from_indices(
                self.coastal_pixel_indices,
                self.townable_mask,
            )

        if pixel is None:
            pixel = self._available_pixel_from_indices(
                self.valid_pixel_indices,
                self.townable_mask,
            )

        if pixel is not None:
            pixel_x, pixel_y = pixel
            loc_x, loc_y = self.pixel_to_center_coords(pixel_x, pixel_y)
            return loc_x, loc_y, self.terrain_at_pixel(pixel_x, pixel_y)

        available_pixels = np.flatnonzero(self.townable_mask & ~self.occupied_mask)
        if available_pixels.size == 0:
            raise Exception("No available townable pixels remain on the map.")

        flat_index = int(available_pixels[random.randrange(available_pixels.size)])
        pixel_y, pixel_x = divmod(flat_index, self.width)
        loc_x, loc_y = self.pixel_to_center_coords(pixel_x, pixel_y)
        return loc_x, loc_y, self.terrain_at_pixel(pixel_x, pixel_y)

    def _town_pixel_growth_priority(
        self,
        center_x,
        center_y,
        pixel_x,
        pixel_y,
        angle,
        stretch,
        town_size=None,
    ):
        dx = pixel_x - center_x
        dy = pixel_y - center_y
        cos_angle = math.cos(angle)
        sin_angle = math.sin(angle)
        along_axis = (dx * cos_angle) + (dy * sin_angle)
        across_axis = (-dx * sin_angle) + (dy * cos_angle)
        shaped_distance = math.sqrt(
            (along_axis / stretch) ** 2 + (across_axis * stretch) ** 2
        )

        terrain = self.terrain_at_pixel(pixel_x, pixel_y)
        if town_size == "Hamlet/Outpost":
            terrain_cost = TOWN_PLACEMENT["hamlet_outpost_terrain_growth_cost"].get(
                terrain,
                TOWN_PLACEMENT["blocked_terrain_growth_cost"],
            )
        else:
            terrain_cost = TOWN_PLACEMENT["normal_terrain_growth_cost"].get(
                terrain,
                TOWN_PLACEMENT["blocked_terrain_growth_cost"],
            )
        edge_noise = random.uniform(
            TOWN_PLACEMENT["growth_edge_noise_min"],
            TOWN_PLACEMENT["growth_edge_noise_max"],
        )
        wobble = TOWN_PLACEMENT["growth_wobble_weight"] * math.sin(
            (pixel_x * TOWN_PLACEMENT["growth_wobble_x_frequency"])
            + (pixel_y * TOWN_PLACEMENT["growth_wobble_y_frequency"])
            + angle
        )
        return shaped_distance + terrain_cost + edge_noise + wobble

    def place_town_footprint(self, town):
        target_pixels = town.target_area_pixels
        center_x, center_y = self.coords_to_pixel(town.loc_x, town.loc_y)
        allowed_mask = self.allowed_footprint_mask_for_town(town)

        if target_pixels <= 0:
            town.footprint_pixels = []
            town.placed_area_pixels = 0
            return
        if not self.is_available_pixel(center_x, center_y, allowed_mask):
            raise Exception(f"{town.name} center is not available for town placement.")

        angle = random.uniform(0.0, math.tau)
        stretch = random.uniform(
            TOWN_PLACEMENT["growth_stretch_min"],
            TOWN_PLACEMENT["growth_stretch_max"],
        )
        footprint = []
        claimed = set()
        queued = set()
        frontier = []

        def claim(pixel_x, pixel_y):
            claimed.add((pixel_x, pixel_y))
            footprint.append((pixel_x, pixel_y))
            self.occupied_mask[pixel_y, pixel_x] = True

        def push_candidate(pixel_x, pixel_y):
            if (pixel_x, pixel_y) in claimed:
                return
            if (pixel_x, pixel_y) in queued:
                return
            if not self.is_available_pixel(pixel_x, pixel_y, allowed_mask):
                return
            priority = self._town_pixel_growth_priority(
                center_x,
                center_y,
                pixel_x,
                pixel_y,
                angle,
                stretch,
                town_size=town.size,
            )
            heapq.heappush(frontier, (priority, random.random(), pixel_x, pixel_y))
            queued.add((pixel_x, pixel_y))

        claim(center_x, center_y)
        for dx, dy in _GROWTH_NEIGHBORS:
            push_candidate(center_x + dx, center_y + dy)

        while len(footprint) < target_pixels and frontier:
            _, _, pixel_x, pixel_y = heapq.heappop(frontier)
            if (pixel_x, pixel_y) in claimed:
                continue
            if not self.is_available_pixel(pixel_x, pixel_y, allowed_mask):
                continue

            claim(pixel_x, pixel_y)
            neighbors = list(_GROWTH_NEIGHBORS)
            random.shuffle(neighbors)
            for dx, dy in neighbors:
                push_candidate(pixel_x + dx, pixel_y + dy)

        town.footprint_pixels = footprint
        town.placed_area_pixels = len(footprint)

    def footprint_touches_water(self, town):
        for pixel_x, pixel_y in town.footprint_pixels:
            for dx, dy in _GROWTH_NEIGHBORS:
                neighbor_x = pixel_x + dx
                neighbor_y = pixel_y + dy
                if (
                    0 <= neighbor_x < self.width
                    and 0 <= neighbor_y < self.height
                    and self.water_mask[neighbor_y, neighbor_x]
                ):
                    return True
        return False

    def designate_town_specialization(self, town):
        if town.size == "Hamlet/Outpost":
            if town.terrain in ("mountains", "snow"):
                town.specialization = "Mining"
            else:
                town.specialization = "Industrial"
            return

        if town.size != "Town" and town.size != "Village":
            if town.size == "City":
                town.specialization = random.choices(
                    [spec[0] for spec in CITY_SPECIALIZATIONS],
                    weights=[spec[1] for spec in CITY_SPECIALIZATIONS],
                )[0]
            return

        terrain_counts = {"beach": 0, "plains": 0, "hills": 0}
        for pixel_x, pixel_y in town.footprint_pixels:
            terrain = self.terrain_at_pixel(pixel_x, pixel_y)
            if terrain in terrain_counts:
                terrain_counts[terrain] += 1

        if terrain_counts["beach"] > 0 or self.footprint_touches_water(town):
            town.specialization = "Fishing"
        elif terrain_counts["hills"] >= max(
            1,
            int(
                town.placed_area_pixels
                * TOWN_PLACEMENT["mining_specialization_hills_fraction"]
            ),
        ):
            town.specialization = "Mining"
        else:
            town.specialization = "Farming"


class Town:
    def __init__(self):
        self.name = townNameGen.generate_town_name()
        self.size, self.population = self.generate_size_and_population()
        self.formatted_population = (
            f"{self.population:,}" if self.population > 0 else "0"
        )
        self.density = self.generate_density()
        self.area = self.population / self.density if self.density > 0 else 0
        (
            self.est_year,
            self.abandoned_year,
        ) = self.generate_establishment_and_abandonment_years()
        self.loc_x, self.loc_y = None, None
        self.terrain = None
        self.footprint_pixels = []
        self.placed_area_pixels = 0
        self.specialization = None

    @property
    def radius_km(self):
        """Approximate the town footprint as a circle with area in sq km."""
        return math.sqrt(self.area / math.pi) if self.area > 0 else 0

    @property
    def target_area_pixels(self):
        return math.ceil(self.area)

    @property
    def display_size(self):
        return self.size
    
    @property
    def display_specialization(self):
        return self.specialization if self.specialization else "None"

    def generate_size_and_population(self):
        size_type, min_pop, max_pop, _ = random.choices(
            town_sizes,
            weights=[s[3] for s in town_sizes],
        )[0]
        population = random.randint(min_pop, max_pop) if max_pop > 0 else 0
        return size_type, population

    def generate_density(self):
        min_density, max_density = town_density[self.size]
        return random.randint(min_density, max_density) if max_density > 0 else 0

    def generate_establishment_and_abandonment_years(self):
        current_year = TOWN_GENERATION["current_year"]
        est_year = random.randint(
            TOWN_GENERATION["established_start_year"],
            current_year - TOWN_GENERATION["minimum_established_age_years"],
        )
        abandoned_year = None

        if self.size == "Ghost Town":
            abandoned_year = random.randint(
                est_year + TOWN_GENERATION["minimum_abandoned_age_years"],
                current_year,
            )

        return est_year, abandoned_year

    def generate_random_coords(self, placement_map=None):
        if placement_map is not None:
            self.loc_x, self.loc_y, self.terrain = placement_map.random_town_center(
                town_size=self.size
            )
            return

        self.loc_x = random.uniform(-MAP_WIDTH / 2, MAP_WIDTH / 2)
        self.loc_y = random.uniform(-MAP_LENGTH / 2, MAP_LENGTH / 2)
        self.terrain = None

    def check_closeness(
        self,
        other_town,
        threshold_km=TOWN_GENERATION["default_spacing_threshold_km"],
    ):
        distance = (
            (self.loc_x - other_town.loc_x) ** 2
            + (self.loc_y - other_town.loc_y) ** 2
        ) ** 0.5
        required_distance = threshold_km + self.radius_km + other_town.radius_km
        return distance < required_distance

    def generate_coords(
        self,
        existing_towns,
        threshold_km=TOWN_GENERATION["default_spacing_threshold_km"],
        placement_map=None,
        max_attempts=TOWN_GENERATION["default_max_attempts"],
    ):
        for _ in range(max_attempts):
            self.generate_random_coords(placement_map=placement_map)
            if all(
                not self.check_closeness(town, threshold_km)
                for town in existing_towns
            ):
                return

        terrain_note = " on valid terrain" if placement_map is not None else ""
        raise Exception(
            "Failed to generate non-overlapping coordinates"
            f"{terrain_note} after many attempts."
        )


def generate_towns(
    town_count=TOWN_GENERATION["default_town_count"],
    heightmap_path=DEFAULT_HEIGHTMAP_PATH,
    threshold_km=TOWN_GENERATION["default_spacing_threshold_km"],
    max_attempts=TOWN_GENERATION["default_max_attempts"],
):
    placement_map = TownPlacementMap.from_file(heightmap_path)
    towns = []

    for _ in range(town_count):
        town = Town()
        town.generate_coords(
            towns,
            threshold_km=threshold_km,
            placement_map=placement_map,
            max_attempts=max_attempts,
        )
        placement_map.place_town_footprint(town)
        placement_map.designate_town_specialization(town)
        towns.append(town)

    return towns, placement_map


def _town_footprint_overlay(towns, placement_map):
    overlay = np.zeros((placement_map.height, placement_map.width, 4), dtype=np.uint8)
    size_colors = {
        "Town": (0, 122, 255, 215),
        "City": (0, 92, 230, 220),
        "Metropolis": (0, 65, 210, 225),
        "Megaopolis": (0, 42, 180, 230),
    }

    for town in towns:
        color = size_colors.get(town.size, (0, 122, 255, 215))
        for pixel_x, pixel_y in town.footprint_pixels:
            overlay[pixel_y, pixel_x] = color

    return overlay


def project_town_to_plot(towns, placement_map=None, output_path=None, show=True):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    fig, ax = plt.subplots(figsize=(12, 12))

    if placement_map is not None:
        extent = (
            -placement_map.width / 2,
            placement_map.width / 2,
            -placement_map.height / 2,
            placement_map.height / 2,
        )
        color_map = render_terrain(
            placement_map.heightmap,
            water_level=placement_map.water_level,
            beach_width=placement_map.beach_width,
        )
        footprint_overlay = _town_footprint_overlay(towns, placement_map)
        ax.imshow(color_map, origin="lower", extent=extent)
        ax.imshow(footprint_overlay, origin="lower", extent=extent)
    else:
        ax.set_xlim(-MAP_WIDTH / 2, MAP_WIDTH / 2)
        ax.set_ylim(-MAP_LENGTH / 2, MAP_LENGTH / 2)

    active_towns = [town for town in towns if not town.abandoned_year]
    abandoned_towns = [town for town in towns if town.abandoned_year]
    if active_towns:
        ax.scatter(
            [town.loc_x for town in active_towns],
            [town.loc_y for town in active_towns],
            s=12,
            color="#0e5749",
            edgecolors="white",
            linewidths=0.5,
            label="Active center",
            zorder=3,
        )
    if abandoned_towns:
        ax.scatter(
            [town.loc_x for town in abandoned_towns],
            [town.loc_y for town in abandoned_towns],
            s=12,
            color="#d7263d",
            edgecolors="white",
            linewidths=0.5,
            label="Abandoned center",
            zorder=3,
        )

    legend_items = [
        Patch(facecolor="#007aff", alpha=0.85, label="Town footprint pixels"),
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor="#0e5749",
            markeredgecolor="white",
            markersize=7,
            label="Active center",
        ),
    ]
    if abandoned_towns:
        legend_items.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor="#d7263d",
                markeredgecolor="white",
                markersize=7,
                label="Abandoned center",
            )
        )

    ax.set_xlabel("X Coordinate (km)")
    ax.set_ylabel("Y Coordinate (km)")
    ax.set_title("Town Footprints Over Terrain")
    ax.legend(handles=legend_items, loc="upper right")
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=180)

    if show:
        plt.show()
    else:
        plt.close(fig)


def project_town_pixels_to_plot(
    towns,
    placement_map,
    output_path=None,
    show=True,
    include_centers=True,
):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    fig, ax = plt.subplots(figsize=(12, 12), facecolor="white")
    ax.set_facecolor("#f7fbff")
    footprint_x = []
    footprint_y = []
    for town in towns:
        for pixel_x, pixel_y in town.footprint_pixels:
            loc_x, loc_y = placement_map.pixel_to_center_coords(pixel_x, pixel_y)
            footprint_x.append(loc_x)
            footprint_y.append(loc_y)

    ax.scatter(
        footprint_x,
        footprint_y,
        s=10,
        marker="s",
        color="#007aff",
        alpha=0.86,
        linewidths=0,
        label="Town footprint pixels",
    )

    if include_centers:
        ax.scatter(
            [town.loc_x for town in towns],
            [town.loc_y for town in towns],
            s=16,
            color="#001f5b",
            edgecolors="white",
            linewidths=0.8,
            zorder=3,
        )

    legend_items = [
        Patch(facecolor="#007aff", alpha=0.85, label="Town footprint pixels"),
    ]
    if include_centers:
        legend_items.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor="#001f5b",
                markeredgecolor="white",
                markersize=7,
                label="Town center",
            )
        )

    ax.set_xlabel("X Coordinate (km)")
    ax.set_ylabel("Y Coordinate (km)")
    ax.set_title("Town Footprint Pixels")
    ax.legend(handles=legend_items, loc="upper right")
    ax.set_xlim(-placement_map.width / 2, placement_map.width / 2)
    ax.set_ylim(-placement_map.height / 2, placement_map.height / 2)
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=180)

    if show:
        plt.show()
    else:
        plt.close(fig)


def print_town_info(town):
    terrain_info = f", Terrain: {town.terrain}" if town.terrain else ""
    footprint_info = (
        f", Town pixels: {town.placed_area_pixels}/{town.target_area_pixels}"
    )
    if town.abandoned_year:
        print(
            f"{town.name} - {town.display_size} (Spec.: {town.display_specialization}) with size {town.area:.2f} sq km "
            f"(radius: {town.radius_km:.2f} km) "
            f"(density: {town.density} per sq km), population "
            f"{town.formatted_population} (Established: {town.est_year}, "
            f"Abandoned: {town.abandoned_year}){terrain_info}{footprint_info}, "
            f"Location: ({town.loc_x:.2f}, {town.loc_y:.2f})"
        )
    else:
        print(
            f"{town.name} - {town.display_size} (Spec.: {town.display_specialization}) with size {town.area:.2f} sq km "
            f"(radius: {town.radius_km:.2f} km) "
            f"(density: {town.density} per sq km), population "
            f"{town.formatted_population} (Established: {town.est_year})"
            f"{terrain_info}{footprint_info}, "
            f"Location: ({town.loc_x:.2f}, {town.loc_y:.2f})"
        )


def export_town_data_to_csv(towns, filename=None):
    import csv

    if filename is None:
        filename = (
            BASE_DIR
            / "csv"
            / f"town_data-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
        )

    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)

    with open(filename, mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "Name",
                "Size",
                "Specialization",
                "Population",
                "Density",
                "Area (sq km)",
                "Radius (km)",
                "Target Area Pixels",
                "Placed Area Pixels",
                "Established Year",
                "Abandoned Year",
                "Terrain",
                "X Coordinate",
                "Y Coordinate",
            ]
        )
        for town in towns:
            writer.writerow(
                [
                    town.name,
                    town.size,
                    town.specialization if town.specialization else "",
                    town.population,
                    town.density,
                    town.area,
                    town.radius_km,
                    town.target_area_pixels,
                    town.placed_area_pixels,
                    town.est_year,
                    town.abandoned_year if town.abandoned_year else "",
                    town.terrain if town.terrain else "",
                    town.loc_x,
                    town.loc_y,
                ]
            )


if __name__ == "__main__":
    existing_towns, town_placement_map = generate_towns(
        TOWN_GENERATION["default_town_count"]
    )

    for town in existing_towns:
        print_town_info(town)

    # export_town_data_to_csv(existing_towns)
    project_town_to_plot(existing_towns, town_placement_map)
