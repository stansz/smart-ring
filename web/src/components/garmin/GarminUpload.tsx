import { useRef, useState } from "react";
import { useGarminUpload } from "../../api/hooks";
import { Card } from "../ui";

type UploadState = "idle" | "uploading" | "success" | "error";

/**
 * Upload zone for Garmin FIT files from a USB-connected watch.
 *
 * Uses `<input webkitdirectory>` so the user selects the Garmin/
 * folder from the watch's USB drive. The code filters on the server
 * side — only Activity/ and Summary/ files are ingested; everything
 * else (Settings, Sports, Metrics, …) is skipped.
 */
export function GarminUpload() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>("idle");
  const [fileCount, setFileCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const mutation = useGarminUpload();

  function handleClick() {
    inputRef.current?.click();
  }

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const fileList = e.target.files;
    if (!fileList || fileList.length === 0) return;

    const files: File[] = [];
    const paths: string[] = [];
    for (let i = 0; i < fileList.length; i++) {
      files.push(fileList[i]);
      paths.push(fileList[i].webkitRelativePath || fileList[i].name);
    }

    setFileCount(files.length);
    setState("uploading");
    setError(null);

    try {
      await mutation.mutateAsync({ files, paths });
      setState("success");
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : "Upload failed");
    }

    // Reset the input so selecting the same folder again triggers onChange
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <Card className="mb-6">
      <div className="p-4 sm:p-5">
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4">
          <button
            type="button"
            onClick={handleClick}
            disabled={state === "uploading"}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg
              bg-blue-600 text-white text-sm font-medium
              hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed
              transition-colors shrink-0"
          >
            {state === "uploading" ? (
              <>
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10"
                    stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Ingesting…
              </>
            ) : (
              <>
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24"
                  stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                Upload from Watch
              </>
            )}
          </button>

          <p className="text-sm text-gray-500 dark:text-gray-400">
            Select the <code className="text-xs bg-gray-100 dark:bg-gray-700 px-1.5 py-0.5 rounded">Garmin</code> folder
            from your watch&apos;s USB drive. Activity &amp; summary files will be ingested.
          </p>
        </div>

        <input
          ref={inputRef}
          type="file"
          // @ts-expect-error webkitdirectory is non-standard but widely supported
          webkitdirectory=""
          multiple
          className="hidden"
          onChange={handleChange}
        />

        {/* Result messages */}
        {state === "success" && (
          <div className="mt-3 p-3 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800">
            <p className="text-sm text-green-800 dark:text-green-300">
              <span className="font-medium">Done.</span>{" "}
              Found {mutation.data?.found ?? 0} activity file{plural(mutation.data?.found ?? 0)}:{" "}
              <span className="font-medium text-green-900 dark:text-green-200">
                {mutation.data?.inserted ?? 0} new
              </span>
              , {mutation.data?.skipped ?? 0} already ingested
              {(mutation.data?.error ?? 0) > 0 && (
                <span className="text-red-700 dark:text-red-400">
                  , {mutation.data?.error} error{(mutation.data?.error ?? 0) > 1 ? "s" : ""}
                </span>
              )}
            </p>
            <button
              type="button"
              onClick={() => setState("idle")}
              className="mt-1 text-xs text-green-700 dark:text-green-400 underline hover:no-underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {state === "uploading" && (
          <div className="mt-3 p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800">
            <p className="text-sm text-blue-800 dark:text-blue-300">
              Uploading {fileCount} file{plural(fileCount)} and ingesting activities…
            </p>
          </div>
        )}

        {state === "error" && (
          <div className="mt-3 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
            <p className="text-sm text-red-800 dark:text-red-300">
              <span className="font-medium">Upload failed:</span> {error}
            </p>
            <button
              type="button"
              onClick={() => setState("idle")}
              className="mt-1 text-xs text-red-700 dark:text-red-400 underline hover:no-underline"
            >
              Dismiss
            </button>
          </div>
        )}
      </div>
    </Card>
  );
}

function plural(n: number): string {
  return n === 1 ? "" : "s";
}
