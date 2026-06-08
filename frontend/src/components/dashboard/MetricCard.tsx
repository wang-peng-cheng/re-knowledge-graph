interface MetricCardProps {
  label: string;
  value: string;
  hint: string;
}

export function MetricCard({ label, value, hint }: MetricCardProps) {
  return (
    <article className="rounded-3xl border border-white/10 bg-white/5 p-4 shadow-glow">
      <p className="text-xs uppercase tracking-[0.24em] text-slate-500">{label}</p>
      <p className="mt-3 text-3xl font-semibold text-white">{value}</p>
      <p className="mt-2 text-sm text-slate-400">{hint}</p>
    </article>
  );
}
