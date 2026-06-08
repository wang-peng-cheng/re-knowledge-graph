"use client";

import { useEffect, useMemo } from "react";

import {
  mockTemporalGraph,
  timelinePulse,
} from "@/constants/mock_temporal_graph";
import { useTimelineController } from "@/hooks/useTimelineController";
import {
  getDashboardMetrics,
  getRelatedEdges,
  getSelectedNode,
  getVisibleGraph,
} from "@/lib/temporal-graph";

import { ForceGraphCanvas } from "./ForceGraphCanvas";
import { MetricCard } from "./MetricCard";
import { TemporalTimeline } from "../timeline/TemporalTimeline";
import { TraceabilityPanel } from "../traceability/TraceabilityPanel";

export function DashboardShell() {
  const {
    currentMoment,
    isPlaying,
    selectedNodeId,
    setSelectedNodeId,
    setTimeIndex,
    timeIndex,
    togglePlaying,
  } = useTimelineController(mockTemporalGraph.timelineMoments);

  const visibleGraph = useMemo(
    () => getVisibleGraph(mockTemporalGraph, currentMoment),
    [currentMoment],
  );

  useEffect(() => {
    const stillVisible = visibleGraph.nodes.some(
      (node) => node.id === selectedNodeId,
    );
    if (stillVisible) {
      return;
    }

    const preferred =
      visibleGraph.nodes.find((node) => node.category === "person") ??
      visibleGraph.nodes.find((node) => node.category === "event") ??
      visibleGraph.nodes[0] ??
      null;

    setSelectedNodeId(preferred?.id ?? null);
  }, [selectedNodeId, setSelectedNodeId, visibleGraph.nodes]);

  const selectedNode = useMemo(
    () => getSelectedNode(visibleGraph.nodes, selectedNodeId),
    [selectedNodeId, visibleGraph.nodes],
  );

  const relatedEdges = useMemo(
    () => getRelatedEdges(visibleGraph.edges, selectedNode?.id ?? null),
    [selectedNode?.id, visibleGraph.edges],
  );

  const metrics = useMemo(
    () => getDashboardMetrics(visibleGraph.nodes, visibleGraph.edges),
    [visibleGraph.edges, visibleGraph.nodes],
  );

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,rgba(76,201,240,0.16),transparent_28%),linear-gradient(180deg,#020617_0%,#06111f_55%,#020617_100%)] text-white">
      <div className="mx-auto flex min-h-screen max-w-[1800px] flex-col gap-5 px-4 py-4 lg:px-6">
        <header className="rounded-[32px] border border-cyan-400/15 bg-slate-950/70 px-6 py-5 shadow-glow backdrop-blur">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/70">
                TKG Multi-Agent Dashboard
              </p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white lg:text-4xl">
                时序舆情图谱多智能体抽取系统
              </h1>
              <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-400">
                面向千万级舆情流的大屏打样，聚焦时序图谱演化、证据溯源与多实体关系联动。
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-300">
              当前场景：{mockTemporalGraph.scenarioTitle}
            </div>
          </div>
        </header>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          <MetricCard
            label="Visible Nodes"
            value={String(metrics.nodeCount)}
            hint="已随时间轴激活的图谱节点"
          />
          <MetricCard
            label="Visible Edges"
            value={String(metrics.edgeCount)}
            hint="当前时间切片中的关系边"
          />
          <MetricCard
            label="People"
            value={String(metrics.personCount)}
            hint="阶段一人物实体活跃数"
          />
          <MetricCard
            label="Events"
            value={String(metrics.eventCount)}
            hint="阶段二事件实体活跃数"
          />
          <MetricCard
            label="Confidence"
            value={`${metrics.avgConfidence}%`}
            hint="当前可见实体平均置信度"
          />
        </section>

        <section className="grid flex-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="flex min-h-[680px] flex-col gap-4 rounded-[32px] border border-white/10 bg-slate-950/55 p-4 shadow-glow backdrop-blur">
            <div className="flex flex-col gap-3 rounded-3xl border border-white/10 bg-white/5 px-4 py-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-cyan-300/70">
                  Composite Graph Stage
                </p>
                <h2 className="mt-2 text-xl font-semibold text-white">
                  主视觉时序动态图谱
                </h2>
                <p className="mt-2 text-sm text-slate-400">
                  人物为阶段一主实体，事件为阶段二主实体；资金、社交、组织节点作为隐含关联支撑层逐步浮现。
                </p>
              </div>
              <div className="rounded-2xl border border-cyan-400/15 bg-cyan-400/10 px-4 py-3 text-sm text-cyan-100">
                演化脉冲：{timelinePulse[timeIndex]}
              </div>
            </div>
            <div className="flex-1">
              <ForceGraphCanvas
                nodes={visibleGraph.nodes}
                edges={visibleGraph.edges}
                selectedNodeId={selectedNode?.id ?? null}
                currentMoment={currentMoment}
                onSelectNode={setSelectedNodeId}
              />
            </div>
          </div>

          <TraceabilityPanel node={selectedNode} relatedEdges={relatedEdges} />
        </section>

        <TemporalTimeline
          timelineMoments={mockTemporalGraph.timelineMoments}
          timeIndex={timeIndex}
          isPlaying={isPlaying}
          pulse={timelinePulse[timeIndex]}
          onChange={setTimeIndex}
          onTogglePlaying={togglePlaying}
        />
      </div>
    </main>
  );
}
