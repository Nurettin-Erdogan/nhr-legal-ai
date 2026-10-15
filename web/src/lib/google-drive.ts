import { inMemoryAccessToken } from "@/lib/auth-api";
export const INTEGRATION_BASE = (import.meta.env.VITE_API_URL ?? "http://localhost:8766").replace(
  /\/$/,
  "",
);
export interface IntegrationConfig {
  drive: { configured: boolean; client_id: string; api_key: string; project_number: string };
  word: { configured: boolean; origin: string; manifest_path: string };
}
export async function loadIntegrationConfig(): Promise<IntegrationConfig> {
  const response = await fetch(`${INTEGRATION_BASE}/api/integrations/config`);
  if (!response.ok) throw new Error("Bağlantı ayarları alınamadı.");
  return response.json();
}
interface GoogleTokenResponse {
  access_token?: string;
  error?: string;
  scope?: string;
}
interface PickerSelection {
  action: string;
  docs?: Array<{ id: string; name: string; mimeType: string }>;
}
interface PickerView {
  setIncludeFolders(value: boolean): PickerView;
  setSelectFolderEnabled(value: boolean): PickerView;
}
interface PickerBuilder {
  setDeveloperKey(key: string): PickerBuilder;
  setAppId(id: string): PickerBuilder;
  setOAuthToken(token: string): PickerBuilder;
  setOrigin(origin: string): PickerBuilder;
  addView(view: PickerView): PickerBuilder;
  enableFeature(feature: string): PickerBuilder;
  setCallback(callback: (selection: PickerSelection) => void): PickerBuilder;
  build(): { setVisible(visible: boolean): void };
}
interface GoogleSDK {
  accounts: {
    oauth2: {
      initTokenClient(options: {
        client_id: string;
        scope: string;
        include_granted_scopes: boolean;
        error_callback: () => void;
        callback: (response: GoogleTokenResponse) => void;
      }): { requestAccessToken(options: { prompt: string }): void };
      hasGrantedAllScopes(response: GoogleTokenResponse, scope: string): boolean;
    };
  };
  picker: {
    PickerBuilder: new () => PickerBuilder;
    DocsView: new () => PickerView;
    Feature: { MULTISELECT_ENABLED: string };
    Action: { CANCEL: string; PICKED: string };
  };
}
declare global {
  interface Window {
    google: GoogleSDK;
    gapi: {
      load(
        name: string,
        options: {
          callback: () => void;
          onerror: () => void;
          timeout: number;
          ontimeout: () => void;
        },
      ): void;
    };
  }
}
const scripts = new Map<string, Promise<void>>();
export function loadGoogleScript(url: string): Promise<void> {
  if (
    !["https://accounts.google.com/gsi/client", "https://apis.google.com/js/api.js"].includes(url)
  )
    throw new Error("Geçersiz Google betik adresi.");
  if (!scripts.has(url))
    scripts.set(
      url,
      new Promise<void>((resolve, reject) => {
        const script = document.createElement("script");
        script.src = url;
        script.async = true;
        script.onload = () => resolve();
        script.onerror = () => {
          scripts.delete(url);
          reject(new Error("Google bağlantı bileşeni yüklenemedi."));
        };
        document.head.appendChild(script);
      }),
    );
  return scripts.get(url)!;
}
export interface PickedDriveFile {
  id: string;
  name: string;
  mimeType: string;
  token: string;
}
export async function prepareDrivePicker() {
  await Promise.all([
    loadGoogleScript("https://accounts.google.com/gsi/client"),
    loadGoogleScript("https://apis.google.com/js/api.js"),
  ]);
  await new Promise<void>((resolve, reject) =>
    window.gapi.load("picker", {
      callback: resolve,
      onerror: () => reject(new Error("Drive seçici yüklenemedi.")),
      timeout: 15000,
      ontimeout: () => reject(new Error("Drive seçici zaman aşımına uğradı.")),
    }),
  );
}
export function pickDriveFiles(config: IntegrationConfig["drive"]): Promise<PickedDriveFile[]> {
  return new Promise((resolve, reject) => {
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: config.client_id,
      scope: "https://www.googleapis.com/auth/drive.file",
      include_granted_scopes: false,
      error_callback: () =>
        reject(new Error("Google bağlantısı iptal edildi veya pencere açılamadı.")),
      callback: (response: GoogleTokenResponse) => {
        if (
          !response.access_token ||
          response.error ||
          !window.google.accounts.oauth2.hasGrantedAllScopes(
            response,
            "https://www.googleapis.com/auth/drive.file",
          )
        )
          return reject(new Error("Seçili Drive dosyaları için erişim verilmedi."));
        const picker = window.google.picker;
        const accessToken = response.access_token;
        try {
          new picker.PickerBuilder()
            .setDeveloperKey(config.api_key)
            .setAppId(config.project_number)
            .setOAuthToken(response.access_token)
            .setOrigin(window.location.origin)
            .addView(new picker.DocsView().setIncludeFolders(true).setSelectFolderEnabled(false))
            .enableFeature(picker.Feature.MULTISELECT_ENABLED)
            .setCallback((result: PickerSelection) => {
              if (result.action === picker.Action.CANCEL) resolve([]);
              if (result.action === picker.Action.PICKED) {
                if (
                  !Array.isArray(result.docs) ||
                  result.docs.some(
                    (item) =>
                      !item ||
                      typeof item.id !== "string" ||
                      typeof item.name !== "string" ||
                      typeof item.mimeType !== "string",
                  )
                )
                  return reject(new Error("Drive dosya seçimi doğrulanamadı."));
                resolve(
                  result.docs.map((item) => ({
                    id: item.id,
                    name: item.name,
                    mimeType: item.mimeType,
                    token: accessToken,
                  })),
                );
              }
            })
            .build()
            .setVisible(true);
        } catch {
          reject(new Error("Drive seçici açılamadı. Google API ayarlarını kontrol edin."));
        }
      },
    });
    client.requestAccessToken({ prompt: "consent" });
  });
}
export async function downloadDriveFile(item: PickedDriveFile): Promise<File> {
  if (!/^[\w-]{5,200}$/.test(item.id)) throw new Error("Geçersiz Drive dosya kimliği.");
  const headers = { Authorization: `Bearer ${item.token}` };
  const metadataResponse = await fetch(
    `https://www.googleapis.com/drive/v3/files/${item.id}?fields=id,name,mimeType,size,capabilities(canDownload)`,
    { headers },
  );
  if (!metadataResponse.ok)
    throw new Error("Drive dosyası okunamadı. Google bağlantısını yenileyin.");
  const metadata = await metadataResponse.json();
  if (metadata.capabilities?.canDownload === false)
    throw new Error("Bu Drive dosyasının indirilmesine izin verilmiyor.");
  const native = metadata.mimeType === "application/vnd.google-apps.document";
  if (metadata.mimeType?.startsWith("application/vnd.google-apps.") && !native)
    throw new Error("Şimdilik Google Dokümanlar ve yüklenmiş belge dosyaları destekleniyor.");
  if (Number(metadata.size) > 50 * 1024 * 1024)
    throw new Error("Drive içe aktarımında dosya başına en fazla 50 MB destekleniyor.");
  const mime = native
    ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    : metadata.mimeType;
  const response = await fetch(
    `https://www.googleapis.com/drive/v3/files/${item.id}${native ? `/export?mimeType=${encodeURIComponent(mime)}` : "?alt=media"}`,
    { headers },
  );
  if (!response.ok) throw new Error("Drive indirmesi tamamlanamadı.");
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let size = 0;
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Drive indirme akışı okunamadı.");
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > 50 * 1024 * 1024) {
        await reader.cancel();
        throw new Error("Drive dosyası 50 MB sınırını aşıyor.");
      }
      chunks.push(new Uint8Array(part.value));
    }
  } finally {
    reader.releaseLock();
  }
  const blob = new Blob(chunks, { type: mime });
  return new File([blob], `${metadata.name}${native ? ".docx" : ""}`, { type: mime });
}
export async function importDriveFile(file: File) {
  const body = new FormData();
  body.append("file", file);
  const token = inMemoryAccessToken();
  const response = await fetch(`${INTEGRATION_BASE}/api/integrations/drive/import`, {
    method: "POST",
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body,
  });
  const result = await response.json().catch(() => null);
  if (!response.ok || typeof result?.id !== "string")
    throw new Error(
      typeof result?.detail === "string" ? result.detail : "Drive belgesi kaydedilemedi.",
    );
  return result;
}
