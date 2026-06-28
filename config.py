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

TRANSPORT_GENERATION = {
    "seed_offset": 7_913,
    # Coarser island detection keeps labeling cheap on large heightmaps.
    "island_detection_stride": 8,
    # Controls extra direct road links after the guaranteed connected backbone.
    # 0.0 produces only the minimum network; 1.0 adds most nearby candidates.
    "road_directness": 0.45,
    "road_neighbor_candidates": 4,
    "road_max_extra_edges_per_town": 2,
    "road_extra_max_nearest_multiplier": 1.8,
    "road_extra_redundant_path_ratio": 1.35,
    "road_redundant_prune_ratio": 1.18,
    "road_sizes_exempt_from_leaf_rule": [
        "Village",
        "Town",
        "City",
        "Metropolis",
        "Megaopolis",
    ],
    "leaf_road_sizes": ["Hamlet/Outpost"],
    "freeway_hub_sizes": ["Metropolis", "Megaopolis"],
    "freeway_served_sizes": ["City", "Metropolis", "Megaopolis"],
    "freeway_fallback_hub_count": 3,
    "freeway_spokes_per_hub": 3,
    "freeway_coverage_radius_km": 900,
    "railway_hub_sizes": ["Metropolis", "Megaopolis"],
    "railway_served_sizes": ["Town", "City", "Metropolis", "Megaopolis"],
    "railway_fallback_hub_count": 4,
    "railway_spokes_per_hub": 4,
    "railway_coverage_radius_km": 1200,
    "railway_min_new_branch_km": 220,
    "air_hub_sizes": ["Metropolis", "Megaopolis"],
    "air_regional_sizes": ["City"],
    "air_connect_regional_cities": True,
    "air_hubs_per_regional_city": 1,
    "air_connect_hubs_fully": True,
    "air_min_route_distance_km": 100,
    "air_max_route_distance_km": 500,
    "air_connect_regional_city_pairs": True,
    "air_regional_min_route_distance_km": 50,
    "air_regional_max_route_distance_km": 250,
    "colors": {
        "road": "#4b5563",
        "bridge": "#2563eb",
        "freeway": "#f97316",
        "railway": "#111827",
        "airway": "#7c3aed",
        "town": "#0f766e",
    },
}

TRANSPORT_ROUTING = {
    "speed_limits_kmh": {
        "road": 60,
        "bridge": 120,
        "freeway": 120,
        "railway": 140,
        "airway": 400,
    },
    "costs": {
        "freeway": {
            "per_km_rate": 0.05,
            "city_entry_fee": 1.00,
            "tolled_city_sizes": ["Town", "Village", "City", "Metropolis", "Megaopolis"],
        },
        "bridge": {
            "per_km_rate": 0.05,
            "base_fee": 1.00,
        },
        "railway": {
            "per_km_rate": 0.10,
            "station_fee": 2.00,
        },
        "airway": {
            "per_km_rate": 0.50,
            "departure_fee": 10.00,
        },
    },
}
