import copy
from collections import deque

from response_models.models import ToolName
from rules.rules_config import RULES_CONFIG
from tools_engine.accessors.graph import EDGE_KINDS, PROFILE_RELATIONS, GraphAccessor
from tools_engine.interface.tool import AbstractTool, InvalidArtifact, InvalidToolArguments, NodeNotFound
from tools_engine.models.tool_result import Completeness, ToolOutput


class GetGraphSubgraph(AbstractTool):
    name = ToolName.Get_Graph_Subgraph

    def execute(self, analysis_context, **kwargs):
        profile = kwargs["PROFILE-ID"]
        seed = kwargs["NODE-ID"]
        depth = kwargs["DEPTH"]
        relation = kwargs.get("RELATION-TYPE")
        direction = kwargs.get("DIRECTION", "both")
        maximum = RULES_CONFIG.max_graph_subgraph_depth
        node_limit = RULES_CONFIG.max_graph_subgraph_nodes
        if (type(maximum) is not int or maximum <= 0 or maximum > 10
                or type(node_limit) is not int or node_limit <= 0 or node_limit > 1000):
            raise InvalidArtifact(details={"artifact": "rules_config"})
        if (not isinstance(profile, str) or not profile or not isinstance(seed, str) or not seed
                or type(depth) is not int or not 0 <= depth <= maximum
                or direction not in {"incoming", "outgoing", "both"}
                or relation is not None and relation not in EDGE_KINDS):
            raise InvalidToolArguments()
        if profile not in PROFILE_RELATIONS:
            raise InvalidToolArguments("PROFILE-ID не поддерживается")
        if relation is not None and relation not in PROFILE_RELATIONS[profile]:
            raise InvalidToolArguments("RELATION-TYPE не поддерживается профилем")
        graph = GraphAccessor(analysis_context).topology(profile)
        if seed not in graph.by_id:
            raise NodeNotFound(details={"node_id": seed})
        edges = [edge for edge in graph.edges if relation is None or edge["kind"] == relation]
        adjacent = {}
        for edge in edges:
            if direction in {"outgoing", "both"}:
                adjacent.setdefault(edge["source_id"], []).append(edge["target_id"])
            if direction in {"incoming", "both"}:
                adjacent.setdefault(edge["target_id"], []).append(edge["source_id"])
        distances = {seed: 0}
        queue = deque((seed,))
        while queue:
            current = queue.popleft()
            if distances[current] == depth:
                continue
            for target in adjacent.get(current, ()):
                if target not in distances:
                    distances[target] = distances[current] + 1
                    queue.append(target)
        ordered = sorted(distances, key=lambda item: (distances[item], item))
        selected = ordered[:node_limit]
        selected_set, all_set = set(selected), set(ordered)
        all_edges = sorted((e for e in edges if e["source_id"] in all_set and e["target_id"] in all_set), key=lambda e: e["id"])
        returned_edges = [e for e in all_edges if e["source_id"] in selected_set and e["target_id"] in selected_set]
        total, returned = len(ordered) + len(all_edges), len(selected) + len(returned_edges)
        result = {
            "root_node_id": seed, "depth": depth, "relation_type": relation, "direction": direction,
            "nodes": [{"distance": distances[item], "node": copy.deepcopy(graph.by_id[item])} for item in selected],
            "edges": copy.deepcopy(returned_edges),
            "counts": {"nodes": {"total": len(ordered), "returned": len(selected)},
                       "edges": {"total": len(all_edges), "returned": len(returned_edges)}},
        }
        return ToolOutput(result, profile_id=profile,
                          completeness=Completeness(returned < total, total, returned))
