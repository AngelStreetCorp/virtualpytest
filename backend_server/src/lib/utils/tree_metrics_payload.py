"""
Tree metrics payload builder.

Single place that turns the aggregated node/edge rows (navigation_metrics_db)
into the JSON the frontend's useMetrics hook consumes, whether the metrics
ride along the combined tree endpoint (`include_metrics=true`) or come from
`GET /server/metrics/tree/<tree_id>`. Both routes must emit the same shape:

    nodes: {node_id: {volume, success_rate, avg_verification_time, confidence}}
    edges: {edge_id#action_set_id: {volume, success_rate, avg_action_time,
                                    avg_kpi_ms, kpi_volume, kpi_report_url, confidence}}
    global_confidence, confidence_distribution {high, medium, low, untested}
"""

from typing import Dict, List, Optional

from shared.src.lib.database.navigation_metrics_db import get_tree_metrics


def calculate_confidence(volume: int, success_rate: float) -> float:
    """Confidence as specified in docs/architecture/navigation_metrics.md:
    25% volume weight (saturates at 10 executions), 75% success rate."""
    volume_weight = min(volume / 10.0, 1.0)
    confidence = (volume_weight * 0.25) + (success_rate * 0.75)
    return min(confidence, 1.0)


def build_tree_metrics_payload(team_id: str, node_ids: List[str], edge_ids: List[str],
                               variant: Optional[str] = None) -> Dict:
    """Fetch metrics for the given ids in one run scope and add confidence fields."""
    metrics = get_tree_metrics(team_id, node_ids, edge_ids, variant)

    processed_nodes = {}
    for node_id, node_metric in metrics['nodes'].items():
        processed_nodes[node_id] = {
            'volume': node_metric['volume'],
            'success_rate': node_metric['success_rate'],
            'avg_verification_time': node_metric['avg_verification_time'],
            'confidence': calculate_confidence(node_metric['volume'], node_metric['success_rate']),
        }

    processed_edges = {}
    for edge_key, edge_metric in metrics['edges'].items():
        processed_edges[edge_key] = {
            'volume': edge_metric['volume'],
            'success_rate': edge_metric['success_rate'],
            'avg_action_time': edge_metric['avg_action_time'],
            'avg_kpi_ms': edge_metric.get('avg_kpi_ms', 0),
            'kpi_volume': edge_metric.get('kpi_volume', 0),
            'kpi_report_url': edge_metric.get('kpi_report_url'),
            'confidence': calculate_confidence(edge_metric['volume'], edge_metric['success_rate']),
        }

    # Weighted global confidence over items that have executions
    all_confidences = []
    all_volumes = []
    for metric in list(processed_nodes.values()) + list(processed_edges.values()):
        if metric['volume'] > 0:
            all_confidences.append(metric['confidence'])
            all_volumes.append(metric['volume'])

    global_confidence = 0.0
    if all_confidences:
        total_weighted = sum(conf * max(vol, 1) for conf, vol in zip(all_confidences, all_volumes))
        total_weight = sum(max(vol, 1) for vol in all_volumes)
        global_confidence = total_weighted / total_weight if total_weight > 0 else 0.0

    # Untested = requested nodes with no executions + requested edges with no
    # executed direction. Edges are keyed per direction (edge_id#action_set_id),
    # so this is counted per edge_id, not per key, to keep the number >= 0.
    tested_edge_ids = {key.split('#', 1)[0] for key, metric in processed_edges.items() if metric['volume'] > 0}
    untested_nodes = sum(1 for metric in processed_nodes.values() if metric['volume'] == 0)
    untested_edges = len(set(edge_ids) - tested_edge_ids)

    return {
        'nodes': processed_nodes,
        'edges': processed_edges,
        'variant': variant,
        'global_confidence': global_confidence,
        'confidence_distribution': {
            'high': sum(1 for conf in all_confidences if conf >= 0.85),
            'medium': sum(1 for conf in all_confidences if 0.65 <= conf < 0.85),
            'low': sum(1 for conf in all_confidences if conf < 0.65),
            'untested': untested_nodes + untested_edges,
        },
    }
