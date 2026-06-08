"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";

import { categoryColorMap, categoryGlyphMap, formatMoment } from "@/lib/temporal-graph";
import { TemporalEdge, TemporalNode } from "@/types/temporal-graph";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full min-h-[480px] items-center justify-center rounded-3xl border border-white/10 bg-slate-950/60">
      <div className="space-y-3 text-center">
        <div className="mx-auto h-12 w-12 animate-pulse rounded-full border border-cyan-400/30 bg-cyan-400/10" />
        <p className="text-sm text-slate-400">正在加载时序图谱引擎...</p>
      </div>
    </div>
  ),
});

interface ForceGraphCanvasProps {
  nodes: TemporalNode[];
  edges: TemporalEdge[];
  selectedNodeId: string | null;
  currentMoment: string;
  onSelectNode: (nodeId: string | null) => void;
}

type RenderNode = TemporalNode & { x?: number; y?: number };

export function ForceGraphCanvas({
  nodes,
  edges,
  selectedNodeId,
  currentMoment,
  onSelectNode,
}: ForceGraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }

      setSize({
        width: entry.contentRect.width,
        height: Math.max(entry.contentRect.height, 480),
      });
    });

    resizeObserver.observe(element);
    return () => resizeObserver.disconnect();
  }, []);

  const graphData = useMemo(
    () => ({
      nodes: nodes.map((node) => ({
        ...node,
        val: node.category === "event" ? 10 : 7,
      })),
      links: edges.map((edge) => ({
        ...edge,
      })),
    }),
    [edges, nodes],
  );

  return (
    <div className="relative h-full min-h-[560px] overflow-hidden rounded-[28px] border border-cyan-400/15 bg-[radial-gradient(circle_at_top,rgba(76,201,240,0.14),transparent_30%),linear-gradient(180deg,rgba(8,17,31,0.95),rgba(2,6,23,0.98))]">
      <div className="pointer-events-none absolute inset-0 bg-grid bg-[size:44px_44px] opacity-40" />
      <div className="pointer-events-none absolute left-5 top-5 z-10 rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 backdrop-blur">
        <p className="text-xs uppercase tracking-[0.3em] text-cyan-300/70">Temporal Snapshot</p>
        <p className="mt-1 text-sm font-medium text-white">{formatMoment(currentMoment)}</p>
        <p className="mt-2 text-xs text-slate-400">点击节点展开溯源，拖动时间轴观察关系涌现。</p>
      </div>
      <div className="pointer-events-none absolute bottom-5 left-5 z-10 flex flex-wrap gap-2">
        {Object.entries(categoryColorMap).map(([key, value]) => (
          <span
            key={key}
            className="rounded-full border border-white/10 bg-slate-950/70 px-3 py-1 text-xs text-slate-200 backdrop-blur"
          >
            <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: value }} />
            {key}
          </span>
        ))}
      </div>
      <div ref={containerRef} className="relative h-full min-h-[560px]">
        {size.width > 0 ? (
          <ForceGraph2D
            width={size.width}
            height={size.height}
            graphData={graphData}
            backgroundColor="rgba(0,0,0,0)"
            cooldownTicks={80}
            d3AlphaDecay={0.045}
            d3VelocityDecay={0.18}
            linkDirectionalParticles={1}
            linkDirectionalParticleWidth={2}
            linkDirectionalParticleColor={() => "rgba(123, 241, 168, 0.65)"}
            linkColor={() => "rgba(133, 214, 255, 0.18)"}
            linkWidth={(link: Record<string, unknown>) =>
              (link.id as string) && (link.id as string).includes("l-2") ? 1.6 : 1.1
            }
            linkLabel={(link: Record<string, unknown>) =>
              `${String(link.relation)} | ${(Number(link.confidence) * 100).toFixed(0)}%`
            }
            nodeCanvasObject={(node: object, ctx: CanvasRenderingContext2D, globalScale: number) => {
              const graphNode = node as RenderNode;
              const radius = graphNode.category === "event" ? 10 : 8;
              const fontSize = 14 / globalScale;
              const label = graphNode.label;
              const color = categoryColorMap[graphNode.category];
              const glyph = categoryGlyphMap[graphNode.category];
              const selected = selectedNodeId === graphNode.id;

              ctx.beginPath();
              ctx.arc(graphNode.x ?? 0, graphNode.y ?? 0, radius, 0, 2 * Math.PI, false);
              ctx.fillStyle = color;
              ctx.shadowColor = color;
              ctx.shadowBlur = selected ? 24 : 12;
              ctx.fill();

              ctx.lineWidth = selected ? 2.5 : 1.1;
              ctx.strokeStyle = selected ? "#ffffff" : "rgba(255,255,255,0.25)";
              ctx.stroke();

              ctx.shadowBlur = 0;
              ctx.font = `600 ${fontSize}px Inter, sans-serif`;
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              ctx.fillStyle = "#03121d";
              ctx.fillText(glyph, graphNode.x ?? 0, graphNode.y ?? 0);

              ctx.font = `500 ${12 / globalScale}px Inter, sans-serif`;
              ctx.textAlign = "left";
              ctx.fillStyle = "rgba(226,232,240,0.95)";
              ctx.fillText(label, (graphNode.x ?? 0) + radius + 6, (graphNode.y ?? 0) + radius + 2);
            }}
            nodePointerAreaPaint={(node: object, color: string, ctx: CanvasRenderingContext2D) => {
              const graphNode = node as RenderNode;
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(graphNode.x ?? 0, graphNode.y ?? 0, 14, 0, 2 * Math.PI, false);
              ctx.fill();
            }}
            onNodeClick={(node: object) => onSelectNode((node as RenderNode).id)}
            onBackgroundClick={() => onSelectNode(null)}
          />
        ) : null}
      </div>
    </div>
  );
}
