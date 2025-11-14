import { motion } from "framer-motion";
import { Image, Download, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { HelpTooltip } from "./HelpTooltip";
import { useMemo, useState } from "react";

interface Screenshot {
  id: string;
  url: string;
  timestamp: string;
  step: string;
}

interface ScreenshotsGalleryProps {
  screenshots: Screenshot[];
}

export const ScreenshotsGallery = ({ screenshots }: ScreenshotsGalleryProps) => {
  const [selectedImage, setSelectedImage] = useState<Screenshot | null>(null);

  // Deduplicate screenshots by step (keep latest screenshot per step)
  const uniqueScreenshots = useMemo(() => {
    const seenSteps = new Set<string>();
    const deduped: Screenshot[] = [];

    for (let i = screenshots.length - 1; i >= 0; i -= 1) {
      const shot = screenshots[i];
      const stepKey = shot.step || `step-${shot.id}`;
      if (!seenSteps.has(stepKey)) {
        seenSteps.add(stepKey);
        deduped.push(shot);
      }
    }

    return deduped.reverse();
  }, [screenshots]);

  const handleDownload = (screenshot: Screenshot) => {
    const link = document.createElement('a');
    link.href = screenshot.url;
    link.download = `screenshot_${screenshot.timestamp}.png`;
    link.click();
  };

  return (
    <>
      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        className="rounded-lg"
      >
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Image className="w-4 h-4 text-primary" />
            <h2 className="text-sm font-semibold">Screenshots</h2>
            <HelpTooltip content="View all screenshots captured during automation steps. Click to enlarge or download." />
          </div>
          <span className="text-xs text-muted-foreground">
            {uniqueScreenshots.length} {uniqueScreenshots.length === 1 ? 'screenshot' : 'screenshots'}
          </span>
        </div>

        {uniqueScreenshots.length === 0 ? (
          <div className="text-center py-12">
            <Image className="w-12 h-12 mx-auto text-muted-foreground/30 mb-3" />
            <p className="text-sm text-muted-foreground">No screenshots yet</p>
            <p className="text-xs text-muted-foreground/70 mt-1">
              Screenshots will appear here during automation
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
            {uniqueScreenshots.map((screenshot) => (
              <motion.div
                key={screenshot.id}
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                whileHover={{ scale: 1.05 }}
                className="relative group cursor-pointer"
                onClick={() => setSelectedImage(screenshot)}
              >
                <Card className="overflow-hidden border-border/50 hover:border-primary/50 transition-all">
                  <div className="aspect-[9/16] relative">
                    <img
                      src={screenshot.url}
                      alt={`Screenshot at ${screenshot.timestamp}`}
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-all flex items-center justify-center opacity-0 group-hover:opacity-100">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDownload(screenshot);
                        }}
                      >
                        <Download className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                  <div className="p-1.5">
                    <p className="text-[10px] text-muted-foreground truncate">{screenshot.step}</p>
                    <p className="text-[10px] text-muted-foreground/70">{screenshot.timestamp}</p>
                  </div>
                </Card>
              </motion.div>
            ))}
          </div>
        )}
      </motion.div>

      {/* Lightbox Modal */}
      {selectedImage && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
          onClick={() => setSelectedImage(null)}
        >
          <Button
            variant="ghost"
            size="icon"
            className="absolute top-4 right-4 text-white hover:bg-white/20"
            onClick={() => setSelectedImage(null)}
          >
            <X className="w-6 h-6" />
          </Button>
          <motion.div
            initial={{ scale: 0.9 }}
            animate={{ scale: 1 }}
            className="max-w-2xl w-full"
            onClick={(e) => e.stopPropagation()}
          >
            <img
              src={selectedImage.url}
              alt={`Screenshot at ${selectedImage.timestamp}`}
              className="w-full rounded-lg shadow-2xl"
            />
            <div className="mt-4 text-center text-white">
              <p className="text-sm font-medium">{selectedImage.step}</p>
              <p className="text-xs text-white/70">{selectedImage.timestamp}</p>
              <Button
                variant="secondary"
                size="sm"
                className="mt-4"
                onClick={() => handleDownload(selectedImage)}
              >
                <Download className="w-4 h-4 mr-2" />
                Download
              </Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </>
  );
};
