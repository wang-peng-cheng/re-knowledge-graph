export type NodeCategory = "person" | "event" | "fund" | "social" | "organization";

export interface TemporalNode {
  id: string;
  label: string;
  category: NodeCategory;
  stage: "stage_one" | "stage_two" | "support";
  validFrom: string;
  confidence: number;
  chunk: string;
  summary: string;
}

export interface TemporalEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  validFrom: string;
  confidence: number;
  chunk: string;
}

export interface TemporalGraphDataset {
  scenarioTitle: string;
  timelineMoments: string[];
  nodes: TemporalNode[];
  edges: TemporalEdge[];
}
