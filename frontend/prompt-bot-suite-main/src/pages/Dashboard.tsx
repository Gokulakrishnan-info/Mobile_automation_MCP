import { useCallback, useEffect, useRef, useState } from "react";
import { DashboardHeader } from "@/components/DashboardHeader";
import { PromptInput } from "@/components/PromptInput";
import { LogsPanel } from "@/components/LogsPanel";
import { DeviceViewer } from "@/components/DeviceViewer";
import { ReportsPanel } from "@/components/ReportsPanel";
import { AnimatedBackground } from "@/components/AnimatedBackground";
import { WelcomeGuide } from "@/components/WelcomeGuide";
import { ScreenshotsGallery } from "@/components/ScreenshotsGallery";
import {
  createAutomationRun,
  getRunEventsUrl,
  checkBackendHealth,
  getRunReport,
  downloadReport,
  getApiBase,
  getDeviceInfo,
  cancelAutomationRun,
} from "@/lib/api";
import { toast } from "sonner";
import { motion } from "framer-motion";

interface Log {
  id: string;
  timestamp: string;
  type: "success" | "error" | "info" | "action";
  message: string;
  details?: string;
  tool?: string;
}

interface Report {
  id: string;
  name: string;
  date: string;
  prompt: string;
  status: "success" | "failed";
  path?: string;
  pdfPath?: string;
}

interface Screenshot {
  id: string;
  url: string;
  timestamp: string;
  step: string;
}

const generateId = () =>
  typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

const Dashboard = () => {
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState<Log[]>([]);
  const [screenUrl, setScreenUrl] = useState<string>();
  const [isLoadingScreen, setIsLoadingScreen] = useState(false);
  const [deviceType, setDeviceType] = useState<"android" | "ios" | null>(null);
  const [deviceName, setDeviceName] = useState<string | null>(null);
  const [isTablet, setIsTablet] = useState<boolean>(false);
  const [screenshots, setScreenshots] = useState<Screenshot[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [showScreenshots, setShowScreenshots] = useState(false);
  const [showReports, setShowReports] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);

  const formatTimestamp = useCallback((value: string) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? new Date().toLocaleTimeString()
      : date.toLocaleTimeString();
  }, []);

  // Utility for appending logs coming from backend events
  const appendLog = useCallback((log: Log) => {
    setLogs((prev) => [...prev, log]);
  }, []);

  const resetRunState = useCallback(() => {
    setLogs([]);
    setScreenshots([]);
    setScreenUrl(undefined);
    // Don't reset device info - keep it throughout automation runs
    // setDeviceType(null);
    // setDeviceName(null);
    // setIsTablet(false);
    setIsLoadingScreen(false);
    setReports([]);
  }, []);

  const handleStopAutomation = async () => {
    if (!activeRunId) {
      toast.warning("No active automation to stop");
      return;
    }

    try {
      await cancelAutomationRun(activeRunId);
      toast.success("Automation stopped successfully");
      setIsRunning(false);
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      toast.error(`Failed to stop automation: ${errorMessage}`);
    }
  };

  const handleRunAutomation = async (prompt: string) => {
    // Check device connection before running automation
    try {
      const deviceInfo = await getDeviceInfo();
      if (!deviceInfo.connected) {
        toast.error("No device connected. Please connect your mobile device via USB and enable USB debugging before running automation.");
        return;
      }
      // Store device name and form factor for display
      if (deviceInfo.devices && deviceInfo.devices.length > 0) {
        const device = deviceInfo.devices[0];
        setDeviceName(device.name || deviceInfo.deviceName);
        setIsTablet(device.isTablet || false);
      } else {
        setDeviceName(deviceInfo.deviceName);
        setIsTablet(false);
      }
    } catch (error) {
      // If we can't check device status, show warning but allow to proceed
      toast.warning("Unable to verify device connection. Proceeding anyway...");
    }

    resetRunState();
    setIsRunning(true);
    setActiveRunId(null);
    eventSourceRef.current?.close();

    try {
      const run = await createAutomationRun({ prompt });
      setActiveRunId(run.id);
      setDeviceType(run.deviceType ?? null);
      setIsRunning(run.status === "pending" || run.status === "running");

      if (run.logs?.length) {
        const hydratedLogs = run.logs.map((entry) => ({
          id: entry.id ?? generateId(),
          timestamp: formatTimestamp(entry.timestamp),
          type: (entry.level ?? "info") as Log["type"],
          message: entry.message,
          details: entry.details ?? undefined,
        }));
        setLogs(hydratedLogs);
      }

      if (run.screenshots?.length) {
        const hydratedScreenshots = run.screenshots.map((entry) => ({
          id: entry.id ?? generateId(),
          url: entry.url,
          timestamp: formatTimestamp(entry.timestamp ?? new Date().toISOString()),
          step: entry.step ?? "Automation step",
        }));
        setScreenshots(hydratedScreenshots);
        const latest = hydratedScreenshots[hydratedScreenshots.length - 1];
        if (latest?.url) {
          setScreenUrl(latest.url);
        }
      }

      toast.success("Automation started. Streaming real-time updates...");
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      appendLog({
        id: Date.now().toString(),
        timestamp: new Date().toLocaleTimeString(),
        type: "error",
        message: "Failed to start automation",
        details: errorMessage,
      });
      toast.error("Failed to start automation");
      setIsRunning(false);
    }
  };

  const handleRefreshScreen = () => {
    if (!activeRunId) {
      toast.info("Start an automation run to view live screen updates.");
      return;
    }
    toast.info("Device screen updates stream automatically during the run.");
  };

  const handleViewReport = async (id: string) => {
    try {
      const apiBase = getApiBase();
      let reportFileName: string | null = null;
      let isPdf = false;

      // First, try to find the report in the reports list
      const report = reports.find((r) => r.id === id);
      
      // Prioritize PDF if available
      if (report?.pdfPath) {
        const pathParts = report.pdfPath.replace(/\\/g, '/').split('/');
        reportFileName = pathParts[pathParts.length - 1] || null;
        isPdf = true;
      } else if (report?.path) {
        // Fallback to JSON if PDF not available
        const pathParts = report.path.replace(/\\/g, '/').split('/');
        reportFileName = pathParts[pathParts.length - 1] || report.name || null;
      } else if (report?.name) {
        reportFileName = report.name;
      }

      // If we have an active run, try to fetch the report from the API
      if (activeRunId) {
        try {
          const reportData = await getRunReport(activeRunId);
          if (reportData) {
            // Prioritize PDF
            if (reportData.pdfPath) {
              const pathParts = reportData.pdfPath.replace(/\\/g, '/').split('/');
              reportFileName = pathParts[pathParts.length - 1] || null;
              isPdf = true;
            } else if (reportData.path) {
              const pathParts = reportData.path.replace(/\\/g, '/').split('/');
              reportFileName = pathParts[pathParts.length - 1] || reportData.name || null;
            } else if (reportData.name) {
              reportFileName = reportData.name;
            }
          }
        } catch (apiError) {
          console.warn("Failed to fetch report from API, using local report data:", apiError);
        }
      }

      // Fallback: try to construct report filename from report ID
      if (!reportFileName && report?.id) {
        // Try PDF first, then JSON
        reportFileName = `${report.id}.pdf`;
        isPdf = true;
      }

      if (!reportFileName) {
        toast.error("Report filename not available. The report may not be generated yet.");
        return;
      }

      // Construct and open the report URL
      const reportUrl = `${apiBase}/reports/${encodeURIComponent(reportFileName)}`;
      
      // Test if the report exists before opening
      try {
        const testResponse = await fetch(reportUrl, { method: 'HEAD' });
        if (!testResponse.ok) {
          // If PDF not found, try JSON
          if (isPdf) {
            const jsonFileName = reportFileName.replace(/\.pdf$/i, '.json');
            const jsonUrl = `${apiBase}/reports/${encodeURIComponent(jsonFileName)}`;
            const jsonTest = await fetch(jsonUrl, { method: 'HEAD' });
            if (jsonTest.ok) {
              window.open(jsonUrl, "_blank");
              toast.success("Opening JSON report (PDF not available)...");
              return;
            }
          }
          toast.error(`Report not found: ${reportFileName}. The file may not exist in the reports directory.`);
          return;
        }
      } catch (fetchError) {
        console.warn("Could not verify report existence, attempting to open anyway:", fetchError);
      }

      window.open(reportUrl, "_blank");
      toast.success(`Opening ${isPdf ? 'PDF' : 'JSON'} report...`);
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      toast.error(`Failed to open report: ${errorMessage}`);
      console.error("Error opening report:", error);
    }
  };

  const handleDownloadReport = async (id: string) => {
    try {
      // Find the report in the reports list
      const report = reports.find((r) => r.id === id);
      if (!report) {
        toast.error("Report not found");
        return;
      }

      let reportFileName: string | null = null;
      let isPdf = false;

      // If we have an active run, try to fetch the report from the API
      if (activeRunId) {
        try {
          const reportData = await getRunReport(activeRunId);
          if (reportData) {
            // Prioritize PDF
            if (reportData.pdfPath) {
              const pathParts = reportData.pdfPath.replace(/\\/g, '/').split('/');
              reportFileName = pathParts[pathParts.length - 1] || null;
              isPdf = true;
            } else if (reportData.path) {
              const pathParts = reportData.path.replace(/\\/g, '/').split('/');
              reportFileName = pathParts[pathParts.length - 1] || reportData.name || null;
            } else if (reportData.name) {
              reportFileName = reportData.name;
            }
          }
        } catch (apiError) {
          console.warn("Failed to fetch report from API, using local report data:", apiError);
        }
      }

      // If report has a path, extract filename (handle both Windows and Unix paths)
      // Prioritize PDF
      if (!reportFileName && report.pdfPath) {
        const pathParts = report.pdfPath.replace(/\\/g, '/').split('/');
        reportFileName = pathParts[pathParts.length - 1] || null;
        isPdf = true;
      } else if (!reportFileName && report.path) {
        const pathParts = report.path.replace(/\\/g, '/').split('/');
        reportFileName = pathParts[pathParts.length - 1] || report.name || null;
      } else if (!reportFileName && report.name) {
        reportFileName = report.name;
      }

      // Fallback: try to construct report filename from report ID
      if (!reportFileName && report.id) {
        reportFileName = `${report.id}.pdf`;
        isPdf = true;
      }

      if (!reportFileName) {
        toast.error("Report filename not available. The report may not be generated yet.");
        return;
      }

      // Download the report using the filename
      const blob = await downloadReport(reportFileName);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      
      // Set appropriate file extension
      const extension = isPdf ? '.pdf' : '.json';
      const baseName = report.name || `report_${id}`;
      link.download = baseName.endsWith(extension) ? baseName : `${baseName}${extension}`;
      
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      toast.success(`Report downloaded successfully! (${isPdf ? 'PDF' : 'JSON'} format)`);
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      toast.error(`Failed to download report: ${errorMessage}`);
    }
  };

  // Check backend connection on mount and fetch device info
  useEffect(() => {
    checkBackendHealth()
      .then((isHealthy) => {
        if (!isHealthy) {
          toast.error(
            "Cannot connect to backend API. Make sure the FastAPI server is running on port 8000.",
            { duration: 5000 }
          );
        }
      })
      .catch(() => {
        // Silently fail - connection check is best effort
      });
    
    // Fetch device info on mount to get device name
    const fetchDeviceInfo = async () => {
      try {
        const deviceInfo = await getDeviceInfo();
        if (deviceInfo.connected && deviceInfo.devices && deviceInfo.devices.length > 0) {
          const device = deviceInfo.devices[0];
          setDeviceName(device.name || deviceInfo.deviceName);
          setIsTablet(device.isTablet || false);
        } else if (deviceInfo.connected) {
          setDeviceName(deviceInfo.deviceName);
          setIsTablet(false);
        }
      } catch (error) {
        // Silently fail - device info fetch is best effort
      }
    };
    fetchDeviceInfo();
  }, []);

  // Set up SSE event stream for active run
  useEffect(() => {
    if (!activeRunId) {
      return;
    }

    const eventsUrl = getRunEventsUrl(activeRunId);
    const source = new EventSource(eventsUrl);
    eventSourceRef.current = source;

    const handleEvent = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data) as Record<string, any>;
        const eventType = payload.type;

        if (eventType === "status") {
          const status = payload.status as
            | "pending"
            | "running"
            | "completed"
            | "failed"
            | "cancelled";
          setIsRunning(status === "pending" || status === "running");
          if (status === "cancelled") {
            toast.info("Automation has been cancelled");
            if (eventSourceRef.current) {
              eventSourceRef.current.close();
              eventSourceRef.current = null;
            }
          }

          if (status === "completed") {
            toast.success("Automation completed");
            eventSourceRef.current?.close();
            eventSourceRef.current = null;
          } else if (status === "failed") {
            toast.error("Automation failed");
            eventSourceRef.current?.close();
            eventSourceRef.current = null;
          } else if (status === "cancelled") {
            toast.warning?.("Automation cancelled");
            eventSourceRef.current?.close();
            eventSourceRef.current = null;
          }
        }

        if (eventType === "device") {
          if (payload.deviceType) {
            setDeviceType(payload.deviceType as "android" | "ios");
          }
          // Update device name and tablet status if provided
          if (payload.deviceName) {
            setDeviceName(payload.deviceName as string);
          }
          if (typeof payload.isTablet === "boolean") {
            setIsTablet(payload.isTablet);
          }
        }

        if (eventType === "log") {
          appendLog({
            id: payload.id ?? generateId(),
            timestamp: formatTimestamp(payload.timestamp ?? new Date().toISOString()),
            type: (payload.level ?? "info") as Log["type"],
            message: payload.message ?? "",
            details: payload.details ?? undefined,
            tool: payload.tool ?? undefined,
          });
        }

        if (eventType === "screenshot" && payload.screenshot) {
          const screenshot = payload.screenshot as Record<string, string>;
          const hydrated: Screenshot = {
            id: screenshot.id ?? generateId(),
            url: screenshot.url,
            timestamp: formatTimestamp(
              screenshot.timestamp ?? new Date().toISOString()
            ),
            step: screenshot.step ?? "Automation step",
          };

          // Filter out OCR screenshots and live screen updates
          const step = hydrated.step?.toLowerCase() || "";
          const url = hydrated.url?.toLowerCase() || "";
          const isOcrScreenshot = 
            url.includes("ocr_search") || 
            url.includes("perception_") ||
            step.includes("ocr");
          const isLiveUpdate =
            step.includes("live screen update") || step.includes("live screen");
          
          if (isLiveUpdate) {
            // For live screen updates, use the URL as-is (backend already includes timestamp)
            // This ensures the screen updates in real-time
            setScreenUrl(hydrated.url);
          } else if (!isOcrScreenshot) {
            // Only add meaningful screenshots to gallery (not OCR, not live updates)
          setScreenshots((prev) => [...prev, hydrated]);
          }
          // OCR screenshots are silently ignored
        }

        if (eventType === "report" && payload.report) {
          const reportPayload = payload.report as Record<string, string>;
          const hydratedReport: Report = {
            id:
              reportPayload.id ?? reportPayload.name ?? generateId(),
            name:
              reportPayload.name ??
              `Automation Report ${new Date().toLocaleString()}`,
            date: reportPayload.createdAt
              ? new Date(reportPayload.createdAt).toLocaleString()
              : new Date().toLocaleString(),
            prompt: reportPayload.prompt ?? "",
            status:
              (reportPayload.status as Report["status"]) ??
              ("success" as Report["status"]),
            path: reportPayload.path ?? undefined,
            pdfPath: reportPayload.pdfPath ?? undefined,
          };
          setReports((prev) => {
            const filtered = prev.filter((item) => item.id !== hydratedReport.id);
            return [hydratedReport, ...filtered];
          });
        }
      } catch (err) {
        console.error("Failed to parse automation event", err);
      }
    };

    const eventTypes = ["status", "device", "log", "screenshot", "report"];
    eventTypes.forEach((type) => source.addEventListener(type, handleEvent));

    source.onerror = (err) => {
      console.error("Automation events stream error", err);
      toast.error("Lost connection to automation stream");
      source.close();
      if (eventSourceRef.current === source) {
        eventSourceRef.current = null;
      }
      setIsRunning(false);
    };

    return () => {
      eventTypes.forEach((type) => source.removeEventListener(type, handleEvent));
      source.close();
      if (eventSourceRef.current === source) {
        eventSourceRef.current = null;
      }
    };
  }, [activeRunId, appendLog, formatTimestamp]);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  return (
    <div className="h-screen bg-background relative overflow-hidden flex flex-col">
      <AnimatedBackground />
      <WelcomeGuide />
      
      <div className="relative z-10 flex flex-col h-full">
        <DashboardHeader
          modelStatus="connected"
          deviceStatus="connected"
          isRunning={isRunning}
          onStop={handleStopAutomation}
        />

        <motion.main 
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5 }}
          className="flex-1 w-full px-4 py-6 overflow-y-auto"
        >
          {/* Main Content Grid - Premium Layout */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-6">
            {/* Left Panel - Prompt Input (3 columns) */}
            <div className="lg:col-span-3">
            <PromptInput onSubmit={handleRunAutomation} isRunning={isRunning} />
          </div>

            {/* Center Panel - Device Viewer (5 columns) */}
            <div className="lg:col-span-5">
            <DeviceViewer
              screenUrl={screenUrl}
              onRefresh={handleRefreshScreen}
              isLoading={isLoadingScreen}
              deviceType={deviceType}
              deviceName={deviceName}
              isTablet={isTablet}
            />
          </div>

            {/* Right Panel - Logs (4 columns) */}
            <div className="lg:col-span-4 h-[calc(100vh-200px)] min-h-[500px]">
            <LogsPanel logs={logs} />
          </div>
        </div>

          {/* Collapsible Screenshots Gallery */}
        <motion.div
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.2 }}
            className="mb-4"
          >
            <div className="glass-panel rounded-2xl p-4 premium-border">
              <button
                onClick={() => setShowScreenshots(!showScreenshots)}
                className="w-full flex items-center justify-between text-base font-bold hover:text-primary transition-all p-2 rounded-xl hover:bg-background/30"
              >
                <span className="flex items-center gap-3">
                  <span className="text-2xl">📸</span>
                  <span>Screenshots</span>
                  <span className="text-sm font-semibold px-2.5 py-1 rounded-full bg-primary/10 text-primary border border-primary/30">
                    {screenshots.length}
                  </span>
                </span>
                <motion.span 
                  animate={{ rotate: showScreenshots ? 180 : 0 }}
                  className="text-muted-foreground text-xl"
                >
                  ▼
                </motion.span>
              </button>
              {showScreenshots && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="mt-3"
        >
          <ScreenshotsGallery screenshots={screenshots} />
                </motion.div>
              )}
            </div>
        </motion.div>

          {/* Collapsible Reports Panel */}
        <motion.div
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.3 }}
          >
            <div className="glass-panel rounded-2xl p-4 premium-border">
              <button
                onClick={() => setShowReports(!showReports)}
                className="w-full flex items-center justify-between text-base font-bold hover:text-primary transition-all p-2 rounded-xl hover:bg-background/30"
              >
                <span className="flex items-center gap-3">
                  <span className="text-2xl">📊</span>
                  <span>Reports</span>
                  <span className="text-sm font-semibold px-2.5 py-1 rounded-full bg-secondary/10 text-secondary border border-secondary/30">
                    {reports.length}
                  </span>
                </span>
                <motion.span 
                  animate={{ rotate: showReports ? 180 : 0 }}
                  className="text-muted-foreground text-xl"
                >
                  ▼
                </motion.span>
              </button>
              {showReports && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  className="mt-3"
        >
          <ReportsPanel
            reports={reports}
            onView={handleViewReport}
            onDownload={handleDownloadReport}
          />
                </motion.div>
              )}
            </div>
        </motion.div>
        </motion.main>
      </div>
    </div>
  );
};

export default Dashboard;
