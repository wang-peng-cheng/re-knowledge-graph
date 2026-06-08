"use client";

import { useEffect, useMemo, useState } from "react";

export function useTimelineController(timelineMoments: string[]) {
  const [timeIndex, setTimeIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  useEffect(() => {
    if (!isPlaying || timelineMoments.length <= 1) {
      return;
    }

    const timer = window.setInterval(() => {
      setTimeIndex((current) => {
        const next = current + 1;
        return next >= timelineMoments.length ? 0 : next;
      });
    }, 1800);

    return () => window.clearInterval(timer);
  }, [isPlaying, timelineMoments.length]);

  const currentMoment = useMemo(
    () => timelineMoments[Math.min(timeIndex, timelineMoments.length - 1)] ?? timelineMoments[0],
    [timeIndex, timelineMoments],
  );

  return {
    timeIndex,
    setTimeIndex,
    currentMoment,
    isPlaying,
    togglePlaying: () => setIsPlaying((value) => !value),
    selectedNodeId,
    setSelectedNodeId,
  };
}
