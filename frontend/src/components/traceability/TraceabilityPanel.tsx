import { formatMoment } from "@/lib/temporal-graph";
import { TemporalEdge, TemporalNode } from "@/types/temporal-graph";

interface TraceabilityPanelProps {
  node: TemporalNode | null;
  relatedEdges: TemporalEdge[];
}

const categoryNameMap: Record<TemporalNode["category"], string> = {
  person: "人物",
  event: "事件",
  fund: "资金",
  social: "社交",
  organization: "组织",
};

export function TraceabilityPanel({ node, relatedEdges }: TraceabilityPanelProps) {
  if (!node) {
    return (
      <aside className="rounded-[28px] border border-white/10 bg-slate-950/75 p-5 shadow-glow">
        <p className="text-xs uppercase tracking-[0.3em] text-cyan-300/70">Traceability Panel</p>
        <div className="mt-5 rounded-3xl border border-dashed border-white/10 bg-white/5 p-6 text-sm text-slate-400">
          点击图谱中的人物或事件节点后，这里会展示其在 TKG 中的生效时间、Agent 置信度和原始文本切块。
        </div>
      </aside>
    );
  }

  return (
    <aside className="rounded-[28px] border border-cyan-400/15 bg-slate-950/75 p-5 shadow-glow">
      <p className="text-xs uppercase tracking-[0.3em] text-cyan-300/70">Traceability Panel</p>
      <div className="mt-4 rounded-3xl border border-white/10 bg-white/5 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-xl font-semibold text-white">{node.label}</h3>
            <p className="mt-1 text-sm text-slate-400">{node.summary}</p>
          </div>
          <span className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs text-cyan-200">
            {categoryNameMap[node.category]}
          </span>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-3 text-sm text-slate-300">
          <div className="rounded-2xl border border-white/10 bg-slate-900/80 p-3">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">valid_from</p>
            <p className="mt-1 font-medium text-white">{formatMoment(node.validFrom)}</p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-slate-900/80 p-3">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">confidence</p>
            <p className="mt-1 font-medium text-white">{Math.round(node.confidence * 100)}%</p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-slate-900/80 p-3">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">chunk</p>
            <p className="mt-2 leading-6 text-slate-300">{node.chunk}</p>
          </div>
        </div>
      </div>

      <div className="mt-5">
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-sm font-medium text-white">关联关系</h4>
          <span className="text-xs text-slate-500">{relatedEdges.length} 条边</span>
        </div>
        <div className="space-y-3">
          {relatedEdges.slice(0, 6).map((edge) => (
            <article key={edge.id} className="rounded-2xl border border-white/10 bg-white/5 p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-slate-200">{edge.relation}</p>
                <span className="text-xs text-cyan-300">{Math.round(edge.confidence * 100)}%</span>
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-400">{edge.chunk}</p>
            </article>
          ))}
        </div>
      </div>
    </aside>
  );
}
