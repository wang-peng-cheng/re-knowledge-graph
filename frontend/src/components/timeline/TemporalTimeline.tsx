"use client";

import { formatMoment } from "@/lib/temporal-graph";

interface TemporalTimelineProps {
  timelineMoments: string[];
  timeIndex: number;
  isPlaying: boolean;
  pulse: string;
  onChange: (nextIndex: number) => void;
  onTogglePlaying: () => void;
}

export function TemporalTimeline({
  timelineMoments,
  timeIndex,
  isPlaying,
  pulse,
  onChange,
  onTogglePlaying,
}: TemporalTimelineProps) {
  const onStep = (direction: -1 | 1) => {
    const next = timeIndex + direction;
    const bounded = Math.max(0, Math.min(timelineMoments.length - 1, next));
    onChange(bounded);
  };

  return (
    <section className="rounded-[28px] border border-cyan-400/15 bg-slate-950/75 px-5 py-5 shadow-glow backdrop-blur">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-cyan-300/70">Temporal Timeline</p>
          <h2 className="mt-2 text-lg font-semibold text-white">舆情演化播放控制台</h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-400">{pulse}</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => onStep(-1)}
            className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:border-cyan-400/40 hover:bg-cyan-400/10"
          >
            上一帧
          </button>
          <button
            type="button"
            onClick={onTogglePlaying}
            className="rounded-full border border-cyan-400/40 bg-cyan-400/12 px-5 py-2 text-sm font-medium text-cyan-200 transition hover:bg-cyan-400/20"
          >
            {isPlaying ? "暂停演化" : "播放演化"}
          </button>
          <button
            type="button"
            onClick={() => onStep(1)}
            className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:border-cyan-400/40 hover:bg-cyan-400/10"
          >
            下一帧
          </button>
        </div>
      </div>

      <div className="mt-5 rounded-3xl border border-white/10 bg-slate-900/80 p-4">
        <div className="mb-4 flex items-center justify-between text-xs uppercase tracking-[0.2em] text-slate-500">
          <span>Current Time</span>
          <span className="text-cyan-300">{formatMoment(timelineMoments[timeIndex] ?? timelineMoments[0])}</span>
        </div>
        <input
          type="range"
          min={0}
          max={timelineMoments.length - 1}
          value={timeIndex}
          onChange={(event) => onChange(Number(event.target.value))}
          className="timeline-range h-2 w-full cursor-pointer appearance-none rounded-full bg-white/10"
        />
        <div className="mt-4 grid grid-cols-2 gap-3 text-xs text-slate-500 md:grid-cols-4 xl:grid-cols-8">
          {timelineMoments.map((moment, index) => {
            const active = index <= timeIndex;
            return (
              <button
                key={moment}
                type="button"
                onClick={() => onChange(index)}
                className={`rounded-2xl border px-3 py-2 text-left transition ${
                  active
                    ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-200"
                    : "border-white/10 bg-white/5 text-slate-500 hover:border-white/20 hover:text-slate-300"
                }`}
              >
                {formatMoment(moment)}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
