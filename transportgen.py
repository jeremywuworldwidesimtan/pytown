from __future__ import annotations

import argparse
import base64
from collections import defaultdict, deque
import csv
from dataclasses import dataclass
from io import BytesIO
import json
import heapq
import math
from pathlib import Path
import random

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

from config import GLOBAL_SEED, TRANSPORT_GENERATION
from towngen import DEFAULT_HEIGHTMAP_PATH, generate_towns

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_TRANSPORT_NETWORK_PATH = BASE_DIR / "web" / "transport_network.png"
DEFAULT_TRANSPORT_OVERLAY_PATH = BASE_DIR / "web" / "transport_overlay.png"
DEFAULT_TRANSPORT_CSV_PATH = BASE_DIR / "csv" / "transport_routes.csv"
TRANSPORT_LAYER_ORDER = ("roads", "bridges", "freeways", "railways", "airways")


@dataclass(frozen=True)
class TransportNode:
    id: int
    town: object
    component_id: int
    is_mainland: bool
    is_island: bool
    is_leaf_town: bool


@dataclass(frozen=True)
class TransportEdge:
    id: int
    a: int
    b: int
    distance_km: float
    route: tuple[tuple[float, float], ...]
    is_bridge: bool = False

    @property
    def key(self):
        return edge_key(self.a, self.b)


@dataclass
class TransportNetwork:
    nodes: list[TransportNode]
    road_edges: list[TransportEdge]
    freeway_edges: list[TransportEdge]
    railway_edges: list[TransportEdge]
    airway_edges: list[TransportEdge]
    mainland_component_id: int | None

    @property
    def road_edge_by_key(self):
        return {edge.key: edge for edge in self.road_edges}


def edge_key(a, b):
    return tuple(sorted((int(a), int(b))))


def _town_distance(town_a, town_b):
    return math.hypot(town_a.loc_x - town_b.loc_x, town_a.loc_y - town_b.loc_y)


def _size_rank(size):
    ranks = {
        "Ghost Town": 0,
        "Hamlet/Outpost": 1,
        "Village": 2,
        "Town": 3,
        "City": 4,
        "Metropolis": 5,
        "Megaopolis": 6,
    }
    return ranks.get(size, 0)


def _label_land_components(placement_map, stride):
    land_mask = ~placement_map.water_mask
    height, width = land_mask.shape
    stride = max(1, int(stride))
    coarse_height = int(math.ceil(height / stride))
    coarse_width = int(math.ceil(width / stride))
    pad_height = (coarse_height * stride) - height
    pad_width = (coarse_width * stride) - width
    padded = np.pad(
        land_mask,
        ((0, pad_height), (0, pad_width)),
        mode="constant",
        constant_values=False,
    )
    coarse_land = padded.reshape(
        coarse_height,
        stride,
        coarse_width,
        stride,
    ).any(axis=(1, 3))

    labels = np.full((coarse_height, coarse_width), -1, dtype=np.int32)
    component_sizes = {}
    component_id = 0
    neighbors = (
        (-1, -1),
        (0, -1),
        (1, -1),
        (-1, 0),
        (1, 0),
        (-1, 1),
        (0, 1),
        (1, 1),
    )

    for start_y in range(coarse_height):
        for start_x in range(coarse_width):
            if not coarse_land[start_y, start_x] or labels[start_y, start_x] != -1:
                continue

            queue = deque([(start_x, start_y)])
            labels[start_y, start_x] = component_id
            size = 0
            while queue:
                x, y = queue.popleft()
                size += 1
                for dx, dy in neighbors:
                    nx = x + dx
                    ny = y + dy
                    if (
                        0 <= nx < coarse_width
                        and 0 <= ny < coarse_height
                        and coarse_land[ny, nx]
                        and labels[ny, nx] == -1
                    ):
                        labels[ny, nx] = component_id
                        queue.append((nx, ny))

            component_sizes[component_id] = size
            component_id += 1

    if not component_sizes:
        return labels, None, stride

    mainland_component_id = max(component_sizes, key=component_sizes.get)
    return labels, mainland_component_id, stride


def _component_at_town(town, placement_map, labels, stride):
    pixel_x, pixel_y = placement_map.coords_to_pixel(town.loc_x, town.loc_y)
    coarse_x = min(pixel_x // stride, labels.shape[1] - 1)
    coarse_y = min(pixel_y // stride, labels.shape[0] - 1)
    component_id = int(labels[coarse_y, coarse_x])
    if component_id >= 0:
        return component_id

    best = None
    for radius in range(1, 4):
        for y in range(max(0, coarse_y - radius), min(labels.shape[0], coarse_y + radius + 1)):
            for x in range(max(0, coarse_x - radius), min(labels.shape[1], coarse_x + radius + 1)):
                candidate = int(labels[y, x])
                if candidate < 0:
                    continue
                distance = math.hypot(x - coarse_x, y - coarse_y)
                if best is None or distance < best[0]:
                    best = (distance, candidate)
        if best is not None:
            return best[1]

    return -1


def _build_nodes(towns, placement_map, settings):
    labels, mainland_component_id, stride = _label_land_components(
        placement_map,
        settings["island_detection_stride"],
    )
    leaf_sizes = set(settings["leaf_road_sizes"])
    leaf_exempt_sizes = set(settings["road_sizes_exempt_from_leaf_rule"])
    nodes = []
    for index, town in enumerate(towns):
        component_id = _component_at_town(town, placement_map, labels, stride)
        is_mainland = mainland_component_id is None or component_id == mainland_component_id
        nodes.append(
            TransportNode(
                id=index,
                town=town,
                component_id=component_id,
                is_mainland=is_mainland,
                is_island=not is_mainland,
                is_leaf_town=town.size in leaf_sizes and town.size not in leaf_exempt_sizes,
            )
        )
    return nodes, mainland_component_id


def _nearest_node_id(source_node, candidate_nodes):
    candidates = [node for node in candidate_nodes if node.id != source_node.id]
    if not candidates:
        return None
    return min(candidates, key=lambda node: _town_distance(source_node.town, node.town)).id


def _minimum_spanning_edge_pairs(nodes):
    if len(nodes) <= 1:
        return []

    by_id = {node.id: node for node in nodes}
    start = max(
        nodes,
        key=lambda node: (_size_rank(node.town.size), getattr(node.town, "population", 0)),
    )
    connected = {start.id}
    remaining = set(by_id) - connected
    heap = []

    def push_edges(from_id):
        from_node = by_id[from_id]
        for to_id in remaining:
            to_node = by_id[to_id]
            distance = _town_distance(from_node.town, to_node.town)
            heapq.heappush(heap, (distance, from_id, to_id))

    push_edges(start.id)
    pairs = []
    while remaining and heap:
        _, a, b = heapq.heappop(heap)
        if b not in remaining:
            continue
        pairs.append(edge_key(a, b))
        connected.add(b)
        remaining.remove(b)
        push_edges(b)

    return pairs


def _make_edge(edge_id, a, b, nodes, is_bridge=False):
    town_a = nodes[a].town
    town_b = nodes[b].town
    return TransportEdge(
        id=edge_id,
        a=a,
        b=b,
        distance_km=_town_distance(town_a, town_b),
        route=((town_a.loc_x, town_a.loc_y), (town_b.loc_x, town_b.loc_y)),
        is_bridge=is_bridge,
    )


def _make_air_edge(edge_id, a, b, nodes):
    town_a = nodes[a].town
    town_b = nodes[b].town
    distance = _town_distance(town_a, town_b)

    return TransportEdge(
        id=edge_id,
        a=a,
        b=b,
        distance_km=distance,
        route=(
            (town_a.loc_x, town_a.loc_y),
            (town_b.loc_x, town_b.loc_y),
        ),
    )


def _nodes_by_component(nodes):
    grouped = defaultdict(list)
    for node in nodes:
        grouped[node.component_id].append(node)
    return grouped


def _component_connection_targets(component_nodes):
    targets = [node for node in component_nodes if not node.is_leaf_town]
    return targets if targets else list(component_nodes)


def _adjacency_from_edge_keys(edge_keys, nodes, excluded_key=None):
    adjacency = defaultdict(list)
    for pair in edge_keys:
        if excluded_key is not None and pair == excluded_key:
            continue
        a, b = pair
        distance = _town_distance(nodes[a].town, nodes[b].town)
        adjacency[a].append((b, distance, pair))
        adjacency[b].append((a, distance, pair))
    return adjacency


def _path_distance_from_edge_keys(edge_keys, nodes, a, b, excluded_key=None):
    adjacency = _adjacency_from_edge_keys(edge_keys, nodes, excluded_key=excluded_key)
    distance, _ = _shortest_path_edge_keys(adjacency, a, b)
    return distance


def _nearest_distance(node, candidates):
    distances = [
        _town_distance(node.town, candidate.town)
        for candidate in candidates
        if candidate.id != node.id
    ]
    return min(distances) if distances else math.inf


def _add_extra_component_roads(edge_keys, component_targets, nodes, settings, rng):
    extra_counts = defaultdict(int)
    for targets in component_targets:
        for node in targets:
            nearest_distance = _nearest_distance(node, targets)
            max_extra_distance = nearest_distance * settings["road_extra_max_nearest_multiplier"]
            candidates = sorted(
                (
                    other
                    for other in targets
                    if other.id != node.id and edge_key(node.id, other.id) not in edge_keys
                ),
                key=lambda other: _town_distance(node.town, other.town),
            )[: settings["road_neighbor_candidates"]]
            for other in candidates:
                if extra_counts[node.id] >= settings["road_max_extra_edges_per_town"]:
                    break
                pair = edge_key(node.id, other.id)
                direct_distance = _town_distance(node.town, other.town)
                if direct_distance > max_extra_distance:
                    continue
                if extra_counts[other.id] >= settings["road_max_extra_edges_per_town"]:
                    continue
                if rng.random() > settings["road_directness"]:
                    continue
                indirect_distance = _path_distance_from_edge_keys(
                    edge_keys,
                    nodes,
                    node.id,
                    other.id,
                )
                if indirect_distance <= direct_distance * settings["road_extra_redundant_path_ratio"]:
                    continue
                edge_keys.add(pair)
                extra_counts[node.id] += 1
                extra_counts[other.id] += 1


def _prune_redundant_road_edges(edge_keys, bridge_keys, protected_keys, nodes, settings):
    removable = sorted(
        (
            pair
            for pair in edge_keys
            if pair not in bridge_keys and pair not in protected_keys
        ),
        key=lambda pair: _town_distance(nodes[pair[0]].town, nodes[pair[1]].town),
        reverse=True,
    )
    for pair in removable:
        if pair not in edge_keys:
            continue
        a, b = pair
        direct_distance = _town_distance(nodes[a].town, nodes[b].town)
        indirect_distance = _path_distance_from_edge_keys(
            edge_keys,
            nodes,
            a,
            b,
            excluded_key=pair,
        )
        if indirect_distance <= direct_distance * settings["road_redundant_prune_ratio"]:
            edge_keys.remove(pair)


def _build_road_edges(nodes, settings, rng):
    non_island = [node for node in nodes if not node.is_island]
    mainland_targets = [node for node in non_island if not node.is_leaf_town]
    if not mainland_targets:
        mainland_targets = non_island[:]

    nodes_by_component = _nodes_by_component(nodes)
    component_targets = []
    edge_keys = set()
    bridge_keys = set()
    protected_keys = set()

    for component_id, component_nodes in nodes_by_component.items():
        targets = _component_connection_targets(component_nodes)
        component_targets.append(targets)
        backbone_pairs = _minimum_spanning_edge_pairs(targets)
        edge_keys.update(backbone_pairs)

        for node in component_nodes:
            if not node.is_leaf_town or node.id in {target.id for target in targets}:
                continue
            target_id = _nearest_node_id(node, targets)
            if target_id is None:
                continue
            pair = edge_key(node.id, target_id)
            edge_keys.add(pair)
            protected_keys.add(pair)

    _add_extra_component_roads(edge_keys, component_targets, nodes, settings, rng)

    mainland_bridge_targets = mainland_targets if mainland_targets else non_island
    for component_id, component_nodes in nodes_by_component.items():
        if component_id == -1 or not any(node.is_island for node in component_nodes):
            continue
        if not mainland_bridge_targets:
            continue
        island_targets = _component_connection_targets(component_nodes)
        bridge_source, bridge_target = min(
            (
                (island_node, mainland_node)
                for island_node in island_targets
                for mainland_node in mainland_bridge_targets
            ),
            key=lambda pair: _town_distance(pair[0].town, pair[1].town),
        )
        pair = edge_key(bridge_source.id, bridge_target.id)
        edge_keys.add(pair)
        bridge_keys.add(pair)
        protected_keys.add(pair)

    _prune_redundant_road_edges(edge_keys, bridge_keys, protected_keys, nodes, settings)

    road_edges = []
    for edge_id, pair in enumerate(sorted(edge_keys)):
        a, b = pair
        road_edges.append(_make_edge(edge_id, a, b, nodes, is_bridge=pair in bridge_keys))
    return road_edges


def _build_road_adjacency(road_edges, allow_bridges=False):
    adjacency = defaultdict(list)
    for edge in road_edges:
        if edge.is_bridge and not allow_bridges:
            continue
        adjacency[edge.a].append((edge.b, edge.distance_km, edge.key))
        adjacency[edge.b].append((edge.a, edge.distance_km, edge.key))
    return adjacency


def _shortest_path_edge_keys(adjacency, source, target):
    heap = [(0.0, source)]
    distances = {source: 0.0}
    previous = {}

    while heap:
        distance, node_id = heapq.heappop(heap)
        if node_id == target:
            break
        if distance > distances.get(node_id, math.inf):
            continue
        for neighbor_id, edge_distance, key in adjacency.get(node_id, []):
            new_distance = distance + edge_distance
            if new_distance < distances.get(neighbor_id, math.inf):
                distances[neighbor_id] = new_distance
                previous[neighbor_id] = (node_id, key)
                heapq.heappush(heap, (new_distance, neighbor_id))

    if target not in distances:
        return math.inf, []

    path = []
    current = target
    while current != source:
        previous_node, key = previous[current]
        path.append(key)
        current = previous_node
    path.reverse()
    return distances[target], path


def _hub_ids(nodes, hub_sizes, served_sizes, fallback_count):
    hubs = [
        node.id
        for node in nodes
        if not node.is_island and node.town.size in set(hub_sizes)
    ]
    if len(hubs) >= 2:
        return hubs

    served = [
        node
        for node in nodes
        if not node.is_island and node.town.size in set(served_sizes)
    ]
    served.sort(
        key=lambda node: (_size_rank(node.town.size), getattr(node.town, "population", 0)),
        reverse=True,
    )
    fallback = [node.id for node in served[: max(2, fallback_count)]]
    merged = []
    for node_id in hubs + fallback:
        if node_id not in merged:
            merged.append(node_id)
    return merged


def _priority_corridor_keys(
    nodes,
    road_edges,
    hub_sizes,
    served_sizes,
    fallback_count,
    spokes_per_hub,
    coverage_radius_km,
    min_new_branch_km=0,
):
    adjacency = _build_road_adjacency(road_edges, allow_bridges=False)
    road_edge_by_key = {edge.key: edge for edge in road_edges}
    hubs = _hub_ids(nodes, hub_sizes, served_sizes, fallback_count)
    if len(hubs) < 2:
        return set()

    path_cache = {}

    def road_path(a, b):
        pair = edge_key(a, b)
        if pair not in path_cache:
            path_cache[pair] = _shortest_path_edge_keys(adjacency, a, b)
        return path_cache[pair]

    corridor_keys = set()
    hub_nodes = [nodes[node_id] for node_id in hubs]
    for pair in _minimum_spanning_edge_pairs(hub_nodes):
        distance, path = road_path(*pair)
        if math.isfinite(distance):
            corridor_keys.update(path)

    served_node_ids = [
        node.id
        for node in nodes
        if not node.is_island and node.town.size in set(served_sizes)
    ]

    for hub_id in hubs:
        candidates = []
        for target_id in served_node_ids:
            if target_id == hub_id:
                continue
            distance, path = road_path(hub_id, target_id)
            if not path or distance > coverage_radius_km:
                continue
            candidates.append((distance, target_id, path))

        selected_count = 0
        for _, _, path in sorted(candidates):
            new_branch_km = sum(
                road_edge_by_key[key].distance_km
                for key in path
                if key not in corridor_keys and key in road_edge_by_key
            )
            if min_new_branch_km and new_branch_km < min_new_branch_km:
                continue
            corridor_keys.update(path)
            selected_count += 1
            if selected_count >= spokes_per_hub:
                break

    return corridor_keys


def _prune_short_terminal_corridors(
    corridor_keys,
    nodes,
    road_edge_by_key,
    protected_node_ids,
    min_branch_km,
):
    if not min_branch_km:
        return corridor_keys

    corridor_keys = set(corridor_keys)
    changed = True
    while changed:
        changed = False
        adjacency = defaultdict(list)
        for key in corridor_keys:
            edge = road_edge_by_key[key]
            adjacency[edge.a].append((edge.b, key))
            adjacency[edge.b].append((edge.a, key))

        terminal_ids = [
            node_id
            for node_id, neighbors in adjacency.items()
            if len(neighbors) == 1 and node_id not in protected_node_ids
        ]
        for terminal_id in terminal_ids:
            if terminal_id not in adjacency or len(adjacency[terminal_id]) != 1:
                continue

            path_keys = []
            total_distance = 0.0
            previous_id = None
            current_id = terminal_id
            while True:
                next_options = [
                    (neighbor_id, key)
                    for neighbor_id, key in adjacency[current_id]
                    if neighbor_id != previous_id
                ]
                if not next_options:
                    break

                next_id, key = next_options[0]
                path_keys.append(key)
                total_distance += road_edge_by_key[key].distance_km
                previous_id, current_id = current_id, next_id
                if current_id in protected_node_ids or len(adjacency[current_id]) != 2:
                    break

            if path_keys and total_distance < min_branch_km:
                corridor_keys.difference_update(path_keys)
                changed = True
                break

    return corridor_keys


def _build_priority_edges(nodes, road_edges, settings, mode):
    keys = _priority_corridor_keys(
        nodes=nodes,
        road_edges=road_edges,
        hub_sizes=settings[f"{mode}_hub_sizes"],
        served_sizes=settings[f"{mode}_served_sizes"],
        fallback_count=settings[f"{mode}_fallback_hub_count"],
        spokes_per_hub=settings[f"{mode}_spokes_per_hub"],
        coverage_radius_km=settings[f"{mode}_coverage_radius_km"],
        min_new_branch_km=settings.get(f"{mode}_min_new_branch_km", 0),
    )
    road_edge_by_key = {edge.key: edge for edge in road_edges}
    if mode == "railway":
        protected_node_ids = set(
            _hub_ids(
                nodes,
                settings[f"{mode}_hub_sizes"],
                settings[f"{mode}_served_sizes"],
                settings[f"{mode}_fallback_hub_count"],
            )
        )
        keys = _prune_short_terminal_corridors(
            keys,
            nodes,
            road_edge_by_key,
            protected_node_ids,
            settings.get(f"{mode}_min_new_branch_km", 0),
        )
    return [road_edge_by_key[key] for key in sorted(keys) if key in road_edge_by_key]


def _build_airway_edges(nodes, settings):
    hub_sizes = set(settings["air_hub_sizes"])
    regional_sizes = set(settings["air_regional_sizes"])
    min_route_distance = settings["air_min_route_distance_km"]
    max_route_distance = settings["air_max_route_distance_km"]
    regional_min_route_distance = settings["air_regional_min_route_distance_km"]
    regional_max_route_distance = settings["air_regional_max_route_distance_km"]
    hub_ids = [
        node.id
        for node in nodes
        if node.town.size in hub_sizes
    ]
    regional_ids = [
        node.id
        for node in nodes
        if node.town.size in regional_sizes
    ]
    if not hub_ids and not regional_ids:
        return []

    def is_allowed_air_route(a, b):
        distance = _town_distance(nodes[a].town, nodes[b].town)
        return min_route_distance <= distance <= max_route_distance

    def is_allowed_regional_air_route(a, b):
        distance = _town_distance(nodes[a].town, nodes[b].town)
        return regional_min_route_distance <= distance <= regional_max_route_distance

    edge_keys = set()
    if hub_ids and settings["air_connect_hubs_fully"]:
        for index, hub_id in enumerate(hub_ids):
            for other_hub_id in hub_ids[index + 1:]:
                if is_allowed_air_route(hub_id, other_hub_id):
                    edge_keys.add(edge_key(hub_id, other_hub_id))
    elif hub_ids:
        for pair in _minimum_spanning_edge_pairs([nodes[node_id] for node_id in hub_ids]):
            if is_allowed_air_route(*pair):
                edge_keys.add(pair)

    if hub_ids and settings["air_connect_regional_cities"]:
        hubs_per_city = max(1, int(settings["air_hubs_per_regional_city"]))
        for regional_id in regional_ids:
            nearest_hubs = sorted(
                (
                    hub_id
                    for hub_id in hub_ids
                    if is_allowed_air_route(regional_id, hub_id)
                ),
                key=lambda hub_id: _town_distance(nodes[regional_id].town, nodes[hub_id].town),
            )[:hubs_per_city]
            for hub_id in nearest_hubs:
                edge_keys.add(edge_key(regional_id, hub_id))

    if settings["air_connect_regional_city_pairs"]:
        for index, regional_id in enumerate(regional_ids):
            for other_regional_id in regional_ids[index + 1:]:
                if is_allowed_regional_air_route(regional_id, other_regional_id):
                    edge_keys.add(edge_key(regional_id, other_regional_id))

    airway_edges = []
    for edge_id, pair in enumerate(sorted(edge_keys)):
        a, b = pair
        airway_edges.append(_make_air_edge(edge_id, a, b, nodes))
    return airway_edges


def generate_transport_network(towns, placement_map, settings=None):
    """Build road, freeway, railway, and airway networks for generated towns."""
    settings = TRANSPORT_GENERATION if settings is None else settings
    rng = random.Random(GLOBAL_SEED + settings["seed_offset"])
    nodes, mainland_component_id = _build_nodes(towns, placement_map, settings)
    road_edges = _build_road_edges(nodes, settings, rng)
    freeway_edges = _build_priority_edges(nodes, road_edges, settings, "freeway")
    railway_edges = _build_priority_edges(nodes, road_edges, settings, "railway")
    airway_edges = _build_airway_edges(nodes, settings)
    return TransportNetwork(
        nodes=nodes,
        road_edges=road_edges,
        freeway_edges=freeway_edges,
        railway_edges=railway_edges,
        airway_edges=airway_edges,
        mainland_component_id=mainland_component_id,
    )


def _screen_route(edge, placement_map):
    return [
        (x + (placement_map.width / 2), (placement_map.height / 2) - y)
        for x, y in edge.route
    ]


def _draw_edges(ax, edges, placement_map, *, color, linewidth, alpha=1.0, zorder=1, linestyle="-"):
    for edge in edges:
        route = _screen_route(edge, placement_map)
        xs = [point[0] for point in route]
        ys = [point[1] for point in route]
        ax.plot(
            xs,
            ys,
            color=color,
            linewidth=linewidth,
            alpha=alpha,
            linestyle=linestyle,
            solid_capstyle="round",
            zorder=zorder,
        )


def _transport_layer_specs(network, transparent):
    colors = TRANSPORT_GENERATION["colors"]
    bridge_edges = [edge for edge in network.road_edges if edge.is_bridge]
    land_road_edges = [edge for edge in network.road_edges if not edge.is_bridge]
    return {
        "roads": {
            "edges": land_road_edges,
            "color": colors["road"],
            "linewidth": 1.1 if transparent else 0.8,
            "alpha": 0.52 if transparent else 0.42,
            "zorder": 1,
            "linestyle": "-",
        },
        "bridges": {
            "edges": bridge_edges,
            "color": colors["bridge"],
            "linewidth": 1.6 if transparent else 1.1,
            "alpha": 0.86,
            "zorder": 2,
            "linestyle": (0, (3, 2)),
        },
        "freeways": {
            "edges": network.freeway_edges,
            "color": colors["freeway"],
            "linewidth": 2.6 if transparent else 1.8,
            "alpha": 0.9,
            "zorder": 3,
            "linestyle": "-",
        },
        "railways": {
            "edges": network.railway_edges,
            "color": colors["railway"],
            "linewidth": 1.5 if transparent else 1.1,
            "alpha": 0.95,
            "zorder": 4,
            "linestyle": (0, (4, 3)),
        },
        "airways": {
            "edges": network.airway_edges,
            "color": colors["airway"],
            "linewidth": 1.2 if transparent else 0.9,
            "alpha": 0.72 if transparent else 0.58,
            "zorder": 5,
            "linestyle": (0, (2, 5)),
        },
    }


def _render_transport(
    network,
    placement_map,
    output_path=None,
    show=True,
    transparent=False,
    max_render_size=None,
    include_towns=True,
    title="Transport Network",
    visible_layers=None,
):
    colors = TRANSPORT_GENERATION["colors"]
    if max_render_size:
        longest_side = max(placement_map.width, placement_map.height)
        scale = min(1.0, max_render_size / longest_side)
    else:
        scale = 1.0
    figure_width = max(1, placement_map.width * scale)
    figure_height = max(1, placement_map.height * scale)
    dpi = 100
    fig = plt.figure(
        figsize=(figure_width / dpi, figure_height / dpi),
        dpi=dpi,
        facecolor="none" if transparent else "white",
    )
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, placement_map.width)
    ax.set_ylim(placement_map.height, 0)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    if not transparent:
        ax.set_facecolor("#f8fafc")

    layer_specs = _transport_layer_specs(network, transparent=transparent)
    if visible_layers is None:
        visible_layers = TRANSPORT_LAYER_ORDER
    for layer_name in visible_layers:
        spec = layer_specs[layer_name]
        _draw_edges(
            ax,
            spec["edges"],
            placement_map,
            color=spec["color"],
            linewidth=spec["linewidth"],
            alpha=spec["alpha"],
            zorder=spec["zorder"],
            linestyle=spec["linestyle"],
        )

    if include_towns:
        xs = [node.town.loc_x + (placement_map.width / 2) for node in network.nodes]
        ys = [(placement_map.height / 2) - node.town.loc_y for node in network.nodes]
        sizes = [12 + (_size_rank(node.town.size) * 6) for node in network.nodes]
        ax.scatter(
            xs,
            ys,
            s=sizes,
            color=colors["town"],
            edgecolors="white",
            linewidths=0.45,
            alpha=0.9,
            zorder=6,
        )

    if not transparent:
        legend_items = [
            Line2D([0], [0], color=colors["road"], linewidth=2, label="Road"),
            Line2D(
                [0],
                [0],
                color=colors["bridge"],
                linewidth=2,
                linestyle=(0, (3, 2)),
                label="Bridge road",
            ),
            Line2D([0], [0], color=colors["freeway"], linewidth=3, label="Freeway"),
            Line2D(
                [0],
                [0],
                color=colors["railway"],
                linewidth=2,
                linestyle=(0, (4, 3)),
                label="Railway",
            ),
            Line2D(
                [0],
                [0],
                color=colors["airway"],
                linewidth=2,
                linestyle=(0, (2, 5)),
                label="Air route",
            ),
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor=colors["town"],
                markeredgecolor="white",
                markersize=7,
                label="Town",
            ),
        ]
        ax.legend(handles=legend_items, loc="upper right", frameon=True)
        ax.set_title(title, pad=10)

    if output_path:
        if hasattr(output_path, "write"):
            fig.savefig(output_path, dpi=dpi, transparent=transparent, format="png")
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(output_path, dpi=dpi, transparent=transparent)

    if show:
        plt.show()
    else:
        plt.close(fig)


def project_transport_network_to_plot(
    network,
    placement_map,
    output_path=DEFAULT_TRANSPORT_NETWORK_PATH,
    show=True,
):
    _render_transport(
        network,
        placement_map,
        output_path=output_path,
        show=show,
        transparent=False,
        max_render_size=None,
        include_towns=True,
        title="Road, Freeway, Railway, and Air Network",
    )


def project_transport_overlay_to_plot(
    network,
    placement_map,
    output_path=DEFAULT_TRANSPORT_OVERLAY_PATH,
    show=False,
    max_render_size=1024,
):
    _render_transport(
        network,
        placement_map,
        output_path=output_path,
        show=show,
        transparent=True,
        max_render_size=max_render_size,
        include_towns=False,
    )


def _layer_output_path(output_path, layer_name):
    output_path = Path(output_path)
    return output_path.with_name(f"{output_path.stem}_{layer_name}{output_path.suffix}")


def project_transport_overlay_layers_to_plots(
    network,
    placement_map,
    output_path=DEFAULT_TRANSPORT_OVERLAY_PATH,
    show=False,
    max_render_size=1024,
):
    layer_paths = {}
    for layer_name in TRANSPORT_LAYER_ORDER:
        layer_path = _layer_output_path(output_path, layer_name)
        _render_transport(
            network,
            placement_map,
            output_path=layer_path,
            show=show,
            transparent=True,
            max_render_size=max_render_size,
            include_towns=False,
            visible_layers=(layer_name,),
        )
        layer_paths[layer_name] = layer_path
    return layer_paths


def transport_overlay_png_data_uri(network, placement_map, max_render_size=1024):
    image_buffer = BytesIO()
    _render_transport(
        network,
        placement_map,
        output_path=image_buffer,
        show=False,
        transparent=True,
        max_render_size=max_render_size,
        include_towns=False,
    )
    encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def transport_overlay_png_data_uris(network, placement_map, max_render_size=1024):
    layer_uris = {}
    for layer_name in TRANSPORT_LAYER_ORDER:
        image_buffer = BytesIO()
        _render_transport(
            network,
            placement_map,
            output_path=image_buffer,
            show=False,
            transparent=True,
            max_render_size=max_render_size,
            include_towns=False,
            visible_layers=(layer_name,),
        )
        encoded = base64.b64encode(image_buffer.getvalue()).decode("ascii")
        layer_uris[layer_name] = f"data:image/png;base64,{encoded}"
    return layer_uris


def network_to_dict(network):
    return {
        "roads": len(network.road_edges),
        "bridges": sum(1 for edge in network.road_edges if edge.is_bridge),
        "freeways": len(network.freeway_edges),
        "railways": len(network.railway_edges),
        "airways": len(network.airway_edges),
        "island_towns": sum(1 for node in network.nodes if node.is_island),
    }


def _transport_route_rows(network, placement_map):
    route_groups = (
        ("road", [edge for edge in network.road_edges if not edge.is_bridge]),
        ("bridge", [edge for edge in network.road_edges if edge.is_bridge]),
        ("freeway", network.freeway_edges),
        ("railway", network.railway_edges),
        ("airway", network.airway_edges),
    )

    for route_type, edges in route_groups:
        for edge in edges:
            node_a = network.nodes[edge.a]
            node_b = network.nodes[edge.b]
            route_coords = [
                {"x": round(x, 2), "y": round(y, 2)}
                for x, y in edge.route
            ]
            screen_coords = [
                {
                    "x": round(x + (placement_map.width / 2), 2),
                    "y": round((placement_map.height / 2) - y, 2),
                }
                for x, y in edge.route
            ]
            yield {
                "route_type": route_type,
                "route_id": f"{route_type}-{edge.id}",
                "edge_id": edge.id,
                "from_town_id": edge.a,
                "from_town_name": node_a.town.name,
                "from_town_size": node_a.town.size,
                "from_component_id": node_a.component_id,
                "to_town_id": edge.b,
                "to_town_name": node_b.town.name,
                "to_town_size": node_b.town.size,
                "to_component_id": node_b.component_id,
                "distance_km": round(edge.distance_km, 3),
                "is_bridge": edge.is_bridge,
                "route_coords_json": json.dumps(route_coords, separators=(",", ":")),
                "screen_coords_json": json.dumps(screen_coords, separators=(",", ":")),
            }


def export_transport_routes_to_csv(network, placement_map, filename):
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "route_type",
        "route_id",
        "edge_id",
        "from_town_id",
        "from_town_name",
        "from_town_size",
        "from_component_id",
        "to_town_id",
        "to_town_name",
        "to_town_size",
        "to_component_id",
        "distance_km",
        "is_bridge",
        "route_coords_json",
        "screen_coords_json",
    ]
    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_transport_route_rows(network, placement_map))
    return filename


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Generate road, freeway, and railway networks for generated towns."
    )
    parser.add_argument("--towns", type=int, default=64)
    parser.add_argument("--heightmap", default=DEFAULT_HEIGHTMAP_PATH)
    parser.add_argument("--network-output", default=DEFAULT_TRANSPORT_NETWORK_PATH)
    parser.add_argument("--overlay-output", default=DEFAULT_TRANSPORT_OVERLAY_PATH)
    parser.add_argument("--export-csv", action="store_true")
    parser.add_argument("--csv-output", default=DEFAULT_TRANSPORT_CSV_PATH)
    parser.add_argument("--max-render-size", type=int, default=1024)
    parser.add_argument("--no-show", action="store_true")
    return parser.parse_args()


def main():
    args = _parse_args()
    towns, placement_map = generate_towns(town_count=args.towns, heightmap_path=args.heightmap)
    network = generate_transport_network(towns, placement_map)
    project_transport_network_to_plot(
        network,
        placement_map,
        output_path=args.network_output,
        show=not args.no_show,
    )
    project_transport_overlay_layers_to_plots(
        network,
        placement_map,
        output_path=args.overlay_output,
        show=False,
        max_render_size=args.max_render_size,
    )
    summary = network_to_dict(network)
    print(
        "Generated transport network: "
        f"{summary['roads']} roads, "
        f"{summary['bridges']} bridges, "
        f"{summary['freeways']} freeway segments, "
        f"{summary['railways']} railway segments, "
        f"{summary['airways']} air routes"
    )
    print(f"Wrote transport network plot to {args.network_output}")
    print(f"Wrote transparent transport overlay layers using base path {args.overlay_output}")
    if args.export_csv:
        export_transport_routes_to_csv(network, placement_map, args.csv_output)
        print(f"Wrote generated transport route CSV to {args.csv_output}")


if __name__ == "__main__":
    main()
