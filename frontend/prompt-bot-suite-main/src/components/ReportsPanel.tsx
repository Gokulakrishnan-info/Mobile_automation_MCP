import { motion } from "framer-motion";
import { FileJson, Download, Eye, Calendar } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { HelpTooltip } from "./HelpTooltip";

interface Report {
  id: string;
  name: string;
  date: string;
  prompt: string;
  status: "success" | "failed";
}

interface ReportsPanelProps {
  reports: Report[];
  onView: (id: string) => void;
  onDownload: (id: string) => void;
}

export const ReportsPanel = ({ reports, onView, onDownload }: ReportsPanelProps) => {
  return (
    <motion.div
      initial={{ y: 20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ delay: 0.2 }}
      whileHover={{ boxShadow: "0 0 30px hsl(var(--glow-secondary) / 0.15)" }}
      className="rounded-lg interactive-card"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <FileJson className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold">Automation Reports</h2>
          <HelpTooltip content="Download or view detailed JSON reports of completed automations. Each report contains all actions, results, and timestamps." />
        </div>
        <Badge variant="secondary" className="bg-muted/50 text-xs">
          {reports.length} Reports
        </Badge>
      </div>

      <ScrollArea className="h-[240px] pr-4">
        <div className="space-y-3">
          {reports.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 text-center p-8">
              <FileJson className="w-12 h-12 text-muted-foreground/30 mb-3" />
              <p className="text-sm font-medium text-muted-foreground mb-1">No reports yet</p>
              <p className="text-xs text-muted-foreground/70 max-w-xs">
                Complete an automation to generate downloadable reports with full execution details
              </p>
            </div>
          ) : (
            reports.map((report, idx) => (
              <motion.div
                key={report.id}
                initial={{ x: -20, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                whileHover={{ scale: 1.02, x: 5 }}
                transition={{ delay: idx * 0.05 }}
                className="p-4 rounded-lg bg-muted/25 hover:bg-muted/35 border border-border/30 hover:border-primary/30 transition-all group cursor-pointer backdrop-blur-sm"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-medium text-sm truncate">{report.name}</h3>
                      <Badge
                        variant={report.status === "success" ? "default" : "destructive"}
                        className="text-xs"
                      >
                        {report.status}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground line-clamp-2 mb-2">
                      {report.prompt}
                    </p>
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Calendar className="w-3 h-3" />
                      <span>{report.date}</span>
                    </div>
                  </div>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => onView(report.id)}
                      className="h-8 w-8 p-0"
                      title="View report details"
                    >
                      <Eye className="w-4 h-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => onDownload(report.id)}
                      className="h-8 w-8 p-0"
                      title="Download JSON report"
                    >
                      <Download className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </motion.div>
            ))
          )}
        </div>
      </ScrollArea>
    </motion.div>
  );
};
