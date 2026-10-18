import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarClock,
  Pause,
  Play,
  XCircle,
  History,
  ArrowUpRight,
} from "lucide-react";
import { api, post, labels } from "./api";
import type { Flow } from "./types";

type Schedule = {
  id: string;
  name: string;
  mode: "once" | "hourly" | "daily";
  status: "active" | "paused" | "completed" | "cancelled";
  nextRun: number | null;
  version: number;
  fired: number;
  skipped: number;
  lastRunId: string | null;
  lastRunStatus: string | null;
};
type Occurrence = {
  id: string;
  scheduledFor: number;
  created: number;
  status: string;
};
const states = {
  active: "Etkin",
  paused: "Duraklatıldı",
  completed: "Tetiklendi",
  cancelled: "İptal edildi",
};
const modes = { once: "Bir kez", hourly: "Her saat", daily: "Her 24 saat" };
export function localInputDate(value = new Date(Date.now() + 300000)) {
  return new Date(value.getTime() - value.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 19);
}
export function scheduleStart(value: string) {
  const date = new Date(value);
  if (
    !value ||
    !Number.isFinite(date.getTime()) ||
    date.getTime() <= Date.now()
  )
    throw Error("Gelecekte bir başlangıç zamanı seç.");
  return date.toISOString();
}
const dateText = (value: number) =>
  new Date(value * 1000).toLocaleString("tr-TR");

export default function Schedules({
  flow,
  canCreate,
  prepare,
  openRun,
}: {
  flow: Flow;
  canCreate: boolean;
  prepare: () => Promise<Flow>;
  openRun: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState(flow.name + " · Zamanlama");
  const [mode, setMode] = useState("once");
  const [start, setStart] = useState(localInputDate);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const pending = useRef<{ signature: string; key: string } | null>(null);
  const schedules = useQuery({
    queryKey: ["schedules", flow.id],
    queryFn: () => api<Schedule[]>(`/workflows/${flow.id}/schedules`),
    refetchInterval: 2000,
  });
  const history = useQuery({
    queryKey: ["schedule-runs", selected],
    queryFn: () => api<Occurrence[]>(`/schedules/${selected}/runs`),
    enabled: !!selected,
    refetchInterval: 2000,
  });

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const startAt = scheduleStart(start);
      if (!name.trim()) throw Error("Zamanlamaya bir ad ver.");
      const saved = await prepare();
      const body = {
        name: name.trim(),
        mode,
        startAt,
        revision: saved.revision,
      };
      const signature = JSON.stringify(body);
      if (pending.current?.signature !== signature)
        pending.current = { signature, key: crypto.randomUUID() };
      await api(`/workflows/${saved.id}/schedules`, {
        ...post(body),
        headers: { "Idempotency-Key": pending.current!.key },
      });
      pending.current = null;
      await qc.invalidateQueries({ queryKey: ["schedules", flow.id] });
      qc.invalidateQueries({ queryKey: ["versions", flow.id] });
      setMessage(
        "Zamanlama kaydedildi. Bu akış sürümü zamanı geldiğinde çalıştırılacak.",
      );
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function change(id: string, action: string) {
    setBusy(true);
    setMessage("");
    try {
      await api(`/schedules/${id}/${action}`, post({}));
      await qc.invalidateQueries({ queryKey: ["schedules", flow.id] });
      setMessage("Zamanlama güncellendi.");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="schedules-panel">
      <p>
        Akışın kaydedilmiş sürümünü otomatik çalıştır. Saat dilimi:{" "}
        <strong>{Intl.DateTimeFormat().resolvedOptions().timeZone}</strong>.
      </p>
      {canCreate ? (
        <form className="schedule-form" onSubmit={create}>
          <label className="field">
            Zamanlama adı
            <input
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
              required
              disabled={busy}
            />
          </label>
          <label className="field">
            Tekrar
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              disabled={busy}
            >
              <option value="once">Bir kez</option>
              <option value="hourly">Her saat</option>
              <option value="daily">Her 24 saat</option>
            </select>
          </label>
          <label className="field">
            İlk çalışma zamanı
            <input
              type="datetime-local"
              step="1"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              required
              disabled={busy}
            />
          </label>
          <button type="submit" className="primary" disabled={busy}>
            <CalendarClock size={15} /> Zamanlamayı kaydet
          </button>
        </form>
      ) : (
        <p className="field-help">
          Yeni zamanlama oluşturmak için taslak akışa dön.
        </p>
      )}
      <p className="field-help">
        Bilgisayar, PostgreSQL, Temporal ve worker açık olmalı. Saatlik/günlük
        tekrarlar 1/24 saatlik sabit aralıklardır. Kaçırılan tekrarlardan
        yalnızca en günceli çalışır; önceki çalışma sürüyorsa o tekrar atlanır.
        Duraklatma veya iptal, başlamış bir çalıştırmayı durdurmaz.
      </p>
      {message && (
        <p role="status" className="schedule-message">
          {message}
        </p>
      )}
      {schedules.isPending && <p>Yükleniyor…</p>}
      {schedules.error && <p role="alert">{schedules.error.message}</p>}
      {schedules.data?.length === 0 && <p>Bu akışta henüz zamanlama yok.</p>}
      <div className="schedule-list">
        {schedules.data?.map((item) => (
          <article className="schedule-card" key={item.id}>
            <div className="schedule-card-title">
              <strong>{item.name}</strong>
              <span>{states[item.status]}</span>
            </div>
            <p>
              {modes[item.mode]} · v{item.version} · {item.fired} tetikleme ·{" "}
              {item.skipped} atlanan tekrar
            </p>
            <p>
              {item.nextRun
                ? `${item.status === "paused" ? "Bekletilen" : "Sonraki"} zaman: ${dateText(item.nextRun)}`
                : "Gelecek çalışma yok."}
            </p>
            {item.lastRunStatus && (
              <p>
                Son çalışma: {labels[item.lastRunStatus] || item.lastRunStatus}
              </p>
            )}
            <div className="schedule-actions">
              {item.status === "active" && (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => change(item.id, "pause")}
                >
                  <Pause size={13} /> Duraklat
                </button>
              )}
              {item.status === "paused" && (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => change(item.id, "resume")}
                >
                  <Play size={13} /> Devam et
                </button>
              )}
              {["active", "paused"].includes(item.status) && (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => change(item.id, "cancel")}
                >
                  <XCircle size={13} /> Zamanlamayı iptal et
                </button>
              )}
              <button
                className="secondary"
                aria-pressed={selected === item.id}
                onClick={() =>
                  setSelected(selected === item.id ? null : item.id)
                }
              >
                <History size={13} /> Zamanlama geçmişi
              </button>
            </div>
            {selected === item.id && (
              <div className="schedule-history">
                {history.error && <p role="alert">{history.error.message}</p>}
                {history.isPending && <p>Geçmiş yükleniyor…</p>}
                {history.data?.length === 0 && <p>Henüz tetikleme yok.</p>}
                {history.data?.map((run) => (
                  <button
                    key={run.id}
                    className="secondary"
                    onClick={() => openRun(run.id)}
                  >
                    {dateText(run.scheduledFor)} ·{" "}
                    {labels[run.status] || run.status}{" "}
                    <ArrowUpRight size={13} />
                  </button>
                ))}
              </div>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
