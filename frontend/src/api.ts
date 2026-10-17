export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Flowforge-Client": "studio",
      ...options.headers,
    },
  });
  if (!response.ok) {
    let message = "İşlem tamamlanamadı.";
    try {
      const data = await response.json();
      message =
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail);
    } catch {}
    throw Error(message);
  }
  return response.json();
}
export const post = (body: unknown) => ({
  method: "POST",
  body: JSON.stringify(body),
});
export const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));
export const labels: Record<string, string> = {
  started: "Başladı",
  retrying: "Tekrar deneniyor",
  error: "Hata",
  completed: "Tamamlandı",
  queued: "Sırada",
  running: "Çalışıyor",
  succeeded: "Tamamlandı",
  failed: "Hata",
  cancelled: "İptal edildi",
  cancelling: "İptal ediliyor",
  skipped: "Atlandı",
  pending: "Bekliyor",
  blocked: "Engellendi",
  ready: "Hazır",
  retry_wait: "Tekrar bekliyor",
};
export const stamp = (value: number) =>
  new Date(value * 1000).toLocaleTimeString("tr-TR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
