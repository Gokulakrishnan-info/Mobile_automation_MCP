const DEFAULT_API_BASE = "http://127.0.0.1:8000";

const apiBase =
  import.meta.env.VITE_AUTOMATION_API_URL?.replace(/\/$/, "") ||
  DEFAULT_API_BASE;

export interface AutomationRun {
  id: string;
  prompt: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  createdAt: string;
  updatedAt: string;
  deviceType?: "android" | "ios" | null;
  reportPath?: string | null;
  logs: Array<{
    id: string;
    level: "info" | "success" | "error" | "action";
    message: string;
    timestamp: string;
    details?: string | null;
  }>;
  screenshots: Array<{
    id: string;
    url: string;
    timestamp: string;
    step?: string | null;
  }>;
}

export interface CreateRunPayload {
  prompt: string;
}

export interface LogEntry {
  id: string;
  level: "info" | "success" | "error" | "action";
  message: string;
  timestamp: string;
  details?: string | null;
}

export interface ScreenshotEntry {
  id: string;
  url: string;
  timestamp: string;
  step?: string | null;
}

export interface ReportEntry {
  id: string;
  name: string;
  path?: string | null;
  pdfPath?: string | null;
  status?: string | null;
  prompt?: string | null;
  createdAt?: string | null;
}

export async function createAutomationRun(
  payload: CreateRunPayload,
  signal?: AbortSignal
): Promise<AutomationRun> {
  const response = await fetch(`${apiBase}/api/runs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to start automation run: ${response.status} ${message}`
    );
  }

  return (await response.json()) as AutomationRun;
}

export async function getAutomationRun(
  runId: string,
  signal?: AbortSignal
): Promise<AutomationRun> {
  const response = await fetch(`${apiBase}/api/runs/${runId}`, { signal });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to fetch automation run: ${response.status} ${message}`
    );
  }
  return (await response.json()) as AutomationRun;
}

export function getRunEventsUrl(runId: string): string {
  return `${apiBase}/api/runs/${runId}/events`;
}

export function getApiBase(): string {
  return apiBase;
}

export function getDefaultApiBase(): string {
  return DEFAULT_API_BASE;
}

export async function checkBackendHealth(
  signal?: AbortSignal
): Promise<boolean> {
  try {
    const response = await fetch(`${apiBase}/health`, {
      signal,
      method: "GET",
    });
    return response.ok && (await response.json()).status === "ok";
  } catch {
    return false;
  }
}

export async function listAutomationRuns(
  signal?: AbortSignal
): Promise<AutomationRun[]> {
  const response = await fetch(`${apiBase}/api/runs`, { signal });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to list automation runs: ${response.status} ${message}`
    );
  }
  return (await response.json()) as AutomationRun[];
}

export async function getRunScreenshots(
  runId: string,
  signal?: AbortSignal
): Promise<ScreenshotEntry[]> {
  const response = await fetch(`${apiBase}/api/runs/${runId}/screenshots`, {
    signal,
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to fetch screenshots: ${response.status} ${message}`
    );
  }
  return (await response.json()) as ScreenshotEntry[];
}

export async function getRunLogs(
  runId: string,
  signal?: AbortSignal
): Promise<LogEntry[]> {
  const response = await fetch(`${apiBase}/api/runs/${runId}/logs`, { signal });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to fetch logs: ${response.status} ${message}`
    );
  }
  return (await response.json()) as LogEntry[];
}

export async function getRunReport(
  runId: string,
  signal?: AbortSignal
): Promise<ReportEntry | null> {
  const response = await fetch(`${apiBase}/api/runs/${runId}/report`, {
    signal,
  });
  if (!response.ok) {
    if (response.status === 404) {
      return null;
    }
    const message = await response.text();
    throw new Error(
      `Failed to fetch report: ${response.status} ${message}`
    );
  }
  const data = await response.json();
  return data as ReportEntry | null;
}

export async function downloadReport(
  reportPath: string,
  signal?: AbortSignal
): Promise<Blob> {
  // Report path should be relative to /reports endpoint
  const reportName = reportPath.split("/").pop() || reportPath;
  const response = await fetch(`${apiBase}/reports/${reportName}`, { signal });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to download report: ${response.status} ${message}`
    );
  }
  return await response.blob();
}

export interface DeviceInfo {
  connected: boolean;
  deviceId?: string | null;
  deviceName: string;
  deviceCount: number;
  devices: Array<{
    id: string;
    name: string;
    model?: string;
    brand?: string;
    isTablet?: boolean;
  }>;
  message?: string;
  error?: string;
}

export async function getDeviceInfo(
  signal?: AbortSignal
): Promise<DeviceInfo> {
  const response = await fetch(`${apiBase}/api/device/info`, { signal });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to fetch device info: ${response.status} ${message}`
    );
  }
  return (await response.json()) as DeviceInfo;
}

export async function cancelAutomationRun(
  runId: string,
  signal?: AbortSignal
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${apiBase}/api/runs/${runId}/cancel`, {
    method: "POST",
    signal,
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(
      `Failed to cancel automation run: ${response.status} ${message}`
    );
  }
  return (await response.json()) as { status: string; message: string };
}

