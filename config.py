"""Central generation settings for map, town, and name generation."""

GLOBAL_SEED = 42

MAP = {
    # Stored as (width, height) in pixels/cells. One pixel is one sq km.
    "size": (4096, 4096),
    "scale": 256.0,
    "sample_step": 4,
    "chunk_rows": 256,
    "exponent": 2,
    "base_height_weight": 0.86,
    "ridge_height_weight": 0.14,
}

MAP_NOISE = {
    "octaves": 6,
    "persistence": 0.5,
    "lacunarity": 2.0,
}

MAP_TERRAIN = {
    "water_level": 0.18,
    "beach_width": 0.04,
    "plains_level": 0.6,
    "hills_level": 0.75,
    "mountains_level": 0.9,
}

MAP_COLORS = {
    "water": (0, 105, 148),
    "beach": (238, 214, 175),
    "plains": (34, 139, 34),
    "hills": (139, 69, 19),
    "mountains": (169, 169, 169),
    "snow": (245, 245, 245),
}

MAP_CONTINENT = {
    "coast_start": 0.72,
    "coast_end": 0.98,
    "edge_power": 2.8,
    "land_floor_above_water": 0.05,
    "coast_roughness": 0.28,
    "coast_noise_scale": 220.0,
    "coast_noise_octaves": 4,
    "coast_noise_persistence": 0.55,
    "coast_noise_lacunarity": 2.0,
    "coast_noise_sample_step_multiplier": 2,
    "coast_noise_min_sample_step": 8,
    "coast_inner_start_offset": -0.22,
    "coast_inner_end_offset": 0.06,
    "coast_outer_start_offset": -0.08,
}

TOWN_GENERATION = {
    "default_town_count": 64,
    "default_spacing_threshold_km": 30,
    "default_max_attempts": 1000,
    "current_year": 2024,
    "established_start_year": 1870,
    "minimum_established_age_years": 50,
    "minimum_abandoned_age_years": 10,
    "metropolis_coastal_bias": 0.5,
    "megaopolis_coastal_bias": 0.7,
}

TOWN_PLACEMENT = {
    "candidate_sample_attempts": 1000,
    "growth_stretch_min": 0.72,
    "growth_stretch_max": 1.38,
    "growth_edge_noise_min": 0.0,
    "growth_edge_noise_max": 0.75,
    "growth_wobble_weight": 0.08,
    "growth_wobble_x_frequency": 0.31,
    "growth_wobble_y_frequency": 0.17,
    "mining_specialization_hills_fraction": 0.20,
    "blocked_terrain_growth_cost": 10_000,
    "normal_terrain_growth_cost": {
        "plains": 0.0,
        "beach": 0.18,
        "hills": 0.28,
    },
    "hamlet_outpost_terrain_growth_cost": {
        "plains": 0.0,
        "hills": 0.16,
        "mountains": 0.0,
        "snow": 0.22,
    },
}

TOWN_SIZES = [
    # Type, min_population, max_population, probability_weight
    ("Ghost Town", 0, 0, 0),
    ("Hamlet/Outpost", 10, 99, 0.05),
    ("Village", 100, 9999, 0.15),
    ("Town", 10000, 99999, 0.5),
    ("City", 100000, 999999, 0.2),
    ("Metropolis", 1000000, 9909999, 0.05),
    ("Megaopolis", 10000000, 50000000, 0.01),
]

TOWN_DENSITY = {
    # Type, min_density, max_density (pop per sq km)
    "Ghost Town": (0, 0),
    "Hamlet/Outpost": (10, 50),
    "Village": (50, 500),
    "Town": (200, 1000),
    "City": (1000, 5000),
    "Metropolis": (10000, 20000),
    "Megaopolis": (20000, 50000),
}

CITY_SPECIALIZATIONS = [
    # Type, probability_weight
    ("Commercial", 0.3),
    ("Industrial", 0.2),
    ("Cultural", 0.1),
    ("Financial", 0.15),
    ("Governmental", 0.05),
    ("Tourism", 0.1),
]

TOWN_NAME_GENERATOR = {
    "suffix_prob": 0,
    "prefix_prob": 0,
    "geo_prob": 0,
    "vowel_start_prob": 0.3,
    "name_length_max": 5,
    "enable_dashes": False,
    "extra_consonant_prob": 0.1,
    "end_consonant_prob": 0.2,
}
