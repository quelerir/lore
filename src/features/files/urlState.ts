import type { InspectorTab } from "./types";

export interface FilesUrlState {
  fileId: string | null;
  runId: string | null;
  chunkId: string | null;
  tab: InspectorTab;
  search: string;
  documentSearch: string;
  status: string;
  fileType: string;
  compareRunId: string | null;
}

export const DEFAULT_FILES_URL_STATE: FilesUrlState = {
  fileId: null,
  runId: null,
  chunkId: null,
  tab: "display",
  search: "",
  documentSearch: "",
  status: "all",
  fileType: "all",
  compareRunId: null,
};

export const readFilesUrlState = (): FilesUrlState => {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab");

  return {
    fileId: params.get("file"),
    runId: params.get("run"),
    chunkId: params.get("chunk"),
    tab:
      tab === "display" ||
      tab === "fulltext" ||
      tab === "vectortext" ||
      tab === "payloads" ||
      tab === "metadata" ||
      tab === "diagnostics"
        ? tab
        : "display",
    search: params.get("search") ?? "",
    documentSearch: params.get("docSearch") ?? "",
    status: params.get("status") ?? "all",
    fileType: params.get("type") ?? "all",
    compareRunId: params.get("compareRun"),
  };
};

export const writeFilesUrlState = (state: FilesUrlState) => {
  const params = new URLSearchParams();

  if (state.fileId) params.set("file", state.fileId);
  if (state.runId) params.set("run", state.runId);
  if (state.chunkId) params.set("chunk", state.chunkId);
  if (state.tab !== "display") params.set("tab", state.tab);
  if (state.search) params.set("search", state.search);
  if (state.documentSearch) params.set("docSearch", state.documentSearch);
  if (state.status !== "all") params.set("status", state.status);
  if (state.fileType !== "all") params.set("type", state.fileType);
  if (state.compareRunId) params.set("compareRun", state.compareRunId);

  const nextUrl = `/files${params.toString() ? `?${params.toString()}` : ""}`;
  window.history.replaceState({}, "", nextUrl);
};
