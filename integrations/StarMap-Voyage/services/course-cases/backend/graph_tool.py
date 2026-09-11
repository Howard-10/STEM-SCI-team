import networkx as nx
import json
from typing import List, Tuple, Dict, Any


def load_graph_from_json(json_path):
    """
    加载一个以 JSON Lines 格式存储的知识图谱文件，并构建一个 networkx 有向图。
    """
    G = nx.DiGraph()
    with open(json_path, 'r', encoding='utf-8') as f:
        # 逐行读取文件，每行都是一个独立的JSON对象
        for line in f:
            try:
                data = json.loads(line)
                if data.get('type') == 'node':
                    # 确保节点ID是字符串，以便一致性
                    node_id = str(data['id'])
                    # 使用节点的所有数据作为属性
                    G.add_node(node_id, **data)
                elif data.get('type') == 'relationship':
                    start_id = str(data['start']['id'])
                    end_id = str(data['end']['id'])
                    # 使用关系的所有数据作为边属性
                    G.add_edge(start_id, end_id, **data)
            except json.JSONDecodeError:
                # 忽略空行或格式不正确的行
                continue
    return G


# 加载图数据（使用文件自身目录作为相对路径基准）
import os
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_PATH = os.path.join(_THIS_DIR, "all_graph_data.json")
G = load_graph_from_json(_DATA_PATH)


# 创建节点名称到ID的映射
def get_node_name_map(graph):
    # 确保访问的是'properties'字典中的'name'字段
    id2name = {str(node_id): graph.nodes[str(node_id)].get('properties', {}).get('name', 'N/A') for node_id in
               graph.nodes}
    name2id = {name: node_id for node_id, name in id2name.items()}
    return id2name, name2id


id2name, name2id = get_node_name_map(G)


def check_concepts_in_graph(concepts: list) -> Tuple[List[str], Dict[str, str]]:
    """
    检查给定的知识点是否都在图谱中。
    """
    missing_concepts = [c for c in concepts if c not in name2id]
    return missing_concepts, name2id


def get_path_between_concepts(concepts: list) -> str:
    """
    给定一个知识点列表，从知识图谱中返回一个有先后序关系的路径。
    """
    missing_concepts, node_id_map = check_concepts_in_graph(concepts)
    if missing_concepts:
        return f"错误：以下知识点在图谱中不存在：{', '.join(missing_concepts)}"

    node_ids = [node_id_map[c] for c in concepts]

    paths = []

    # 遍历所有节点对，寻找路径
    for i in range(len(node_ids) - 1):
        start_node = node_ids[i]
        end_node = node_ids[i + 1]

        try:
            shortest_path = nx.shortest_path(G, source=start_node, target=end_node)
            paths.append([id2name[node_id] for node_id in shortest_path])
        except nx.NetworkXNoPath:
            return f"错误：在知识点 '{id2name[start_node]}' 和 '{id2name[end_node]}' 之间找不到路径，请重新指定知识点或检查图谱。"

    return paths


def get_all_concepts() -> List[str]:
    return list(name2id.keys())


def get_prerequisites(concept: str, max_depth: int = 2) -> Dict[str, Any]:
    """
    给定一个知识点名称，返回其前驱路径（先修知识）。
    - 返回格式：{"concept": 概念名, "prerequisites": [[路径1按顺序的节点名], [路径2...]]}
    - max_depth: 限制最长路径步数，避免过深遍历
    """
    missing_concepts, node_id_map = check_concepts_in_graph([concept])
    if missing_concepts:
        return {
            "error": f"错误：以下知识点在图谱中不存在：{', '.join(missing_concepts)}"
        }

    start_id = node_id_map[concept]

    # 反向图上做有界 DFS/BFS，收集从任何前驱到 start 的路径
    reversed_graph = G.reverse(copy=False)

    collected_paths: List[List[str]] = []

    def dfs(current_id: str, path: List[str], depth: int):
        if depth > max_depth:
            return
        path.append(current_id)
        # 记录一条从某前驱到起点的路径（反向到正向需要翻转）
        if current_id != start_id:
            collected_paths.append([id2name[nid] for nid in list(reversed(path))])
        for predecessor in reversed_graph.successors(current_id):
            if predecessor in path:
                continue
            dfs(predecessor, path.copy(), depth + 1)

    dfs(start_id, [], 0)

    # 去重（可能存在多条相同路径）
    unique = []
    seen = set()
    for p in collected_paths:
        key = tuple(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return {"concept": concept, "prerequisites": unique}


def get_postrequisites(concept: str, max_depth: int = 2) -> Dict[str, Any]:
    """
    给定一个知识点名称，返回其后继路径（后续学习）。
    - 返回格式：{"concept": 概念名, "postrequisites": [[路径1按顺序的节点名], [路径2...]]}
    - max_depth: 限制最长路径步数
    """
    missing_concepts, node_id_map = check_concepts_in_graph([concept])
    if missing_concepts:
        return {
            "error": f"错误：以下知识点在图谱中不存在：{', '.join(missing_concepts)}"
        }

    start_id = node_id_map[concept]

    collected_paths: List[List[str]] = []

    def dfs(current_id: str, path: List[str], depth: int):
        if depth > max_depth:
            return
        path.append(current_id)
        if current_id != start_id:
            collected_paths.append([id2name[nid] for nid in path])
        for successor in G.successors(current_id):
            if successor in path:
                continue
            dfs(successor, path.copy(), depth + 1)

    dfs(start_id, [], 0)

    unique = []
    seen = set()
    for p in collected_paths:
        key = tuple(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return {"concept": concept, "postrequisites": unique}