"use client";

import { useEffect, useRef, useState } from "react";
import { CorpusStats } from "@/lib/api";

function formatCount(value: number | undefined) {
  if (value == null) return "—";
  return value.toLocaleString("tr-TR");
}

function useFineHover() {
  const [fine, setFine] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(hover: hover) and (pointer: fine)");
    const sync = () => setFine(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);
  return fine;
}

export default function CorpusPill({ stats }: { stats: CorpusStats | null }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const fineHover = useFineHover();

  useEffect(() => {
    if (!openId) return;
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpenId(null);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpenId(null);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [openId]);

  const items = [
    {
      id: "decisions",
      label: "yargı kararı",
      value: stats ? stats.decision_count + (stats.seed_count ?? 0) : undefined,
      lines: [
        { label: "Resmî portaldan doğrulanmış", value: formatCount(stats?.decision_count) },
        { label: "· Yargıtay", value: formatCount(stats?.court_decisions?.yargitay) },
        { label: "· Danıştay", value: formatCount(stats?.court_decisions?.danistay) },
        { label: "· Anayasa Mahkemesi", value: formatCount(stats?.court_decisions?.anayasa_mahkemesi) },
        {
          label: "Üçüncü taraf arşiv, resmî portalla doğrulanmadı",
          value: formatCount(stats?.seed_count),
        },
      ],
    },
    {
      id: "administrative",
      label: "idarî karar",
      value: stats?.other_count,
      lines: [
        {
          label: "Kamu Denetçiliği Kurumu",
          value: formatCount(stats?.administrative?.kamu_denetciligi_kurumu),
        },
      ],
    },
    {
      id: "legislation",
      label: "doğrulanmış mevzuat",
      value: stats?.legislation_count,
      lines: [
        { label: "Bedesten", value: formatCount(stats?.legislation_verification?.bedesten) },
        {
          label: "İkisi de doğruladı",
          value: formatCount(stats?.legislation_verification?.both_verified),
        },
        {
          label: "Sadece Resmî Gazete",
          value: formatCount(stats?.legislation_verification?.gazette_only),
        },
        {
          label: "Sadece Mevzuat Bilgi Sis.",
          value: formatCount(stats?.legislation_verification?.mbs_only),
        },
        {
          label: "İkisi de henüz doğrulanmadı",
          value: formatCount(stats?.legislation_verification?.neither),
        },
      ],
    },
    {
      id: "chunks",
      label: "parça",
      value: stats?.chunk_count,
      lines: [
        { label: "Embedding hazır", value: formatCount(stats?.embeddings?.ready) },
        { label: "Bekleyen", value: formatCount(stats?.embeddings?.pending) },
      ],
    },
  ];

  return (
    <div
      className="corpus-pill"
      ref={rootRef}
      onMouseLeave={() => {
        if (fineHover) setOpenId(null);
      }}
    >
      {items.map((item, index) => {
        const open = openId === item.id;
        return (
          <span key={item.id} className={`corpus-stat-wrap${index >= 2 ? " end" : ""}`}>
            {index > 0 ? <span className="corpus-sep" aria-hidden="true">·</span> : null}
            <button
              type="button"
              className={`corpus-stat-trigger${open ? " open" : ""}`}
              aria-expanded={open}
              onMouseEnter={() => {
                if (fineHover) setOpenId(item.id);
              }}
              onClick={() => {
                if (!fineHover) setOpenId((current) => (current === item.id ? null : item.id));
              }}
              onFocus={() => {
                if (fineHover) setOpenId(item.id);
              }}
            >
              <strong>{formatCount(item.value)}</strong> {item.label}
            </button>
            {open ? (
              <div className="corpus-tooltip" role="tooltip">
                <ul>
                  {item.lines.map((line) => (
                    <li key={line.label}>
                      <span>{line.label}</span>
                      <strong>{line.value}</strong>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </span>
        );
      })}
    </div>
  );
}
