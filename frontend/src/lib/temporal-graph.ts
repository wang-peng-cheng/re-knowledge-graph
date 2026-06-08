import { TemporalEdge, TemporalGraphDataset, TemporalNode } from "@/types/temporal-graph";

export const categoryColorMap: Record<TemporalNode["category"], string> = {
  person: "#4cc9f0",
  event: "#ff6b81",
  fund: "#ffd166",
  social: "#7bf1a8",
  organization: "#c792ea",
};

export const categoryGlyphMap: Record<TemporalNode["category"], string> = {
  person: "P",
  event: "E",
  fund: "F",
  social: "S",
  organization: "O",
};

const toTime = (value: string) => new Date(value).getTime();

export function getVisibleGraph(dataset: TemporalGraphDataset, currentMoment: string) {
  const threshold = toTime(currentMoment);
  const nodes = dataset.nodes.filter((node) => toTime(node.validFrom) <= threshold);
  const visibleIds = new Set(nodes.map((node) => node.id));
  const edges = dataset.edges.filter(
    (edge) =>
      toTime(edge.validFrom) <= threshold &&
      visibleIds.has(edge.source) &&
      visibleIds.has(edge.target),
  );

  return { nodes, edges };
}

export function getSelectedNode(nodes: TemporalNode[], selectedNodeId: string | null) {
  if (!selectedNodeId) {
    return nodes.find((node) => node.category === "person") ?? null;
  }

  return nodes.find((node) => node.id === selectedNodeId) ?? null;
}

export function getRelatedEdges(edges: TemporalEdge[], nodeId: string | null) {
  if (!nodeId) {
    return [];
  }

  return edges.filter((edge) => edge.source === nodeId || edge.target === nodeId);
}

export function getDashboardMetrics(nodes: TemporalNode[], edges: TemporalEdge[]) {
  const personCount = nodes.filter((node) => node.category === "person").length;
  const eventCount = nodes.filter((node) => node.category === "event").length;
  const avgConfidence = nodes.length
    ? Math.round((nodes.reduce((sum, node) => sum + node.confidence, 0) / nodes.length) * 100)
    : 0;

  return {
    nodeCount: nodes.length,
    edgeCount: edges.length,
    personCount,
    eventCount,
    avgConfidence,
  };
}

export function formatMoment(moment: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(moment));
}
