import json
import networkx as nx

def load_graph_from_json(json_path):
    G = nx.DiGraph()
    with open(json_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    for line in lines:
        data = json.loads(line)
        if data["type"] == "node":
            node_id = str(data["id"])
            node_name = data["properties"]["name"]
            G.add_node(node_id, name=node_name)
        elif data["type"] == "relationship":
            start_id = str(data["start"]["id"])
            end_id = str(data["end"]["id"])
            label = data.get("label", "")
            G.add_edge(start_id, end_id, label=label)
    return G

def get_node_name_map(G):
    id_to_name = {n: G.nodes[n]["name"] for n in G.nodes}
    name_to_id = {v: k for k, v in id_to_name.items()}
    return id_to_name, name_to_id
