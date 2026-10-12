import { useEffect, useRef, useState } from "react";

// Side-by-side source viewer (design doc 19.1): renders the cited PDF page next to a value so a
// reviewer can check it. PDF.js loads lazily to keep the main bundle small.
export function SourceViewer({ url, page }: { url: string; page: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        const worker = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
        const doc = await pdfjs.getDocument({ url }).promise;
        const p = await doc.getPage(page);
        const viewport = p.getViewport({ scale: 1.25 });
        const el = canvas.current;
        if (!el || cancelled) return;
        el.width = viewport.width;
        el.height = viewport.height;
        await p.render({ canvas: el, viewport }).promise;
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [url, page]);

  return error ? (
    <p className="error">{error}</p>
  ) : (
    <canvas ref={canvas} aria-label={`Page ${page}`} />
  );
}
