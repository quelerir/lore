import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ListCollapse,
  ListTree,
  X,
  CircleHelp,
  Copy,
  FileWarning,
  Filter,
  FolderSearch,
  Image as ImageIcon,
  MessageSquarePlus,
  Rows3,
  Search,
  Table2,
  UserRound,
} from "lucide-react";
import styles from "./FilesPage.module.css";
import { mockFiles } from "./mockData";
import {
  clearAllComments,
  deleteComment,
  getReviewerName,
  listComments,
  setReviewerName,
  upsertComment,
} from "./reviewStorage";
import { DEFAULT_FILES_URL_STATE, readFilesUrlState, writeFilesUrlState } from "./urlState";
import type {
  FileChunk,
  FileImagePayload,
  FileRecord,
  FileRun,
  FileTablePayload,
  FileTranscriptPayload,
  InspectorTab,
  ReviewComment,
  ReviewVerdict,
} from "./types";

interface FilesPageProps {
  onNavigateHome: () => void;
}

interface CommentDraft {
  verdict: ReviewVerdict;
  categories: string;
  text: string;
  quote: string;
}

const commentCategories = [
  "граница чанка",
  "потеря контекста",
  "отображение",
  "полный текст",
  "векторный текст",
  "таблица",
  "изображение",
  "диагностика",
  "другое",
];

const inspectorTabs: Array<{ id: InspectorTab; label: string }> = [
  { id: "display", label: "Отображение" },
  { id: "fulltext", label: "Полный текст" },
  { id: "vectortext", label: "Векторный текст" },
  { id: "payloads", label: "Связанные данные" },
  { id: "metadata", label: "Метаданные" },
  { id: "diagnostics", label: "Диагностика" },
];

const formatRunTime = (value: string) =>
  new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));

const formatStatus = (status: FileRun["status"]) => {
  switch (status) {
    case "success":
      return "Успешно";
    case "active":
      return "В обработке";
    case "failed":
      return "Ошибка";
    case "skipped":
      return "Пропущено";
  }
};

const formatChunkType = (type: string) => {
  switch (type) {
    case "heading":
      return "заголовок";
    case "table":
      return "таблица";
    case "figure":
      return "изображение";
    default:
      return type;
  }
};

const formatChunkCardType = (type: string) => {
  switch (type) {
    case "heading":
      return "section";
    case "table":
      return "table";
    case "figure":
      return "figure";
    default:
      return type;
  }
};

const formatChunkMetaLabel = (chunk: FileChunk) => {
  const parts: string[] = [];

  if (chunk.metadata.page) {
    parts.push(`page ${chunk.metadata.page}`);
  }

  parts.push(`${chunk.type} ${chunk.ordinal}`);
  parts.push(`${chunk.tokenCount} токенов`);

  return parts.join(" · ");
};

const getChunkCardContent = (chunk: FileChunk) => {
  const lines = simpleMarkdown(chunk.displayText)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  return {
    title: lines[0] ?? chunk.section,
    preview: lines.slice(1).join(" "),
  };
};

const getChunkAttachmentPreview = (run: FileRun, chunk: FileChunk) => {
  const tableRef = chunk.payloads.find((payload) => payload.type === "table");
  if (tableRef) {
    const table = run.tables.find((item) => item.id === tableRef.id);
    if (table) {
      return { kind: "table" as const, table };
    }
  }

  const imageRef = chunk.payloads.find((payload) => payload.type === "image");
  if (imageRef) {
    const image = run.images.find((item) => item.id === imageRef.id);
    if (image) {
      return { kind: "image" as const, image };
    }
  }

  return null;
};

const getRunSeverity = (status: FileRun["status"]) => {
  switch (status) {
    case "success":
      return styles.success;
    case "active":
      return styles.active;
    case "failed":
      return styles.failed;
    case "skipped":
      return styles.skipped;
  }
};

const getTextByTab = (chunk: FileChunk, tab: InspectorTab) => {
  if (tab === "display") return chunk.displayText;
  if (tab === "fulltext") return chunk.fullText;
  return chunk.vectorText;
};

const simpleMarkdown = (text: string) =>
  text
    .split("\n")
    .map((line) => line.replace(/^#\s+/, "").replace(/^\*\*(.+)\*\*:/, "$1:"))
    .join("\n");

const copyText = async (value: string) => {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Fall through to the legacy selection-based copy path.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-9999px";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
};

const makeLineDiff = (leftText: string, rightText: string) => {
  const leftLines = leftText.split("\n");
  const rightLines = rightText.split("\n");
  const length = Math.max(leftLines.length, rightLines.length);

  return Array.from({ length }, (_, index) => ({
    left: leftLines[index] ?? "",
    right: rightLines[index] ?? "",
    changed: (leftLines[index] ?? "") !== (rightLines[index] ?? ""),
  }));
};

const deriveFileStats = (file: FileRecord, comments: ReviewComment[]) => {
  const latestRun = file.runs[0];
  const fileComments = comments.filter((comment) => comment.fileId === file.id);
  const diagnostics = latestRun.chunks.reduce(
    (count, chunk) => count + chunk.diagnostics.length,
    0,
  );
  const autoFindings = latestRun.chunks.reduce(
    (count, chunk) => count + chunk.findings.length,
    0,
  );

  return {
    latestRun,
    commentCount: fileComments.length,
    chunkCount: latestRun.chunks.length,
    tableCount: latestRun.tables.length,
    imageCount: latestRun.images.length,
    diagnostics,
    autoFindings,
  };
};

export default function FilesPage({ onNavigateHome: _onNavigateHome }: FilesPageProps) {
  const initialUrlState = readFilesUrlState();
  const [search, setSearch] = useState(initialUrlState.search);
  const [documentSearch, setDocumentSearch] = useState(initialUrlState.documentSearch);
  const [statusFilter, setStatusFilter] = useState(initialUrlState.status);
  const [fileTypeFilter, setFileTypeFilter] = useState(initialUrlState.fileType);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(initialUrlState.fileId);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialUrlState.runId);
  const [selectedChunkId, setSelectedChunkId] = useState<string | null>(initialUrlState.chunkId);
  const [selectedTab, setSelectedTab] = useState<InspectorTab>(initialUrlState.tab);
  const [compareRunId, setCompareRunId] = useState<string | null>(initialUrlState.compareRunId);
  const [comments, setComments] = useState<ReviewComment[]>([]);
  const [reviewerName, setReviewerNameState] = useState("");
  const [reviewerDraft, setReviewerDraft] = useState("");
  const [needsReviewerModal, setNeedsReviewerModal] = useState(false);
  const [commentDraft, setCommentDraft] = useState<CommentDraft>({
    verdict: "question",
    categories: "",
    text: "",
    quote: "",
  });
  const [textMode, setTextMode] = useState<"rendered" | "raw">("rendered");
  const [diffTarget, setDiffTarget] = useState<"none" | "fulltext" | "vectortext" | "display">(
    "none",
  );
  const [diffMode, setDiffMode] = useState<"side-by-side" | "unified">("side-by-side");
  const [isReviewDrawerOpen, setIsReviewDrawerOpen] = useState(false);
  const [isChunkMetaVisible, setIsChunkMetaVisible] = useState(true);

  useEffect(() => {
    void listComments().then(setComments);
    void getReviewerName().then((name) => {
      setReviewerNameState(name);
      setReviewerDraft(name);
      setNeedsReviewerModal(!name);
    });
  }, []);

  const filteredFiles = useMemo(() => {
    return mockFiles.filter((file) => {
      const latestRun = file.runs[0];
      const matchesSearch =
        !search ||
        file.name.toLowerCase().includes(search.toLowerCase()) ||
        file.pipeline.toLowerCase().includes(search.toLowerCase());
      const matchesStatus = statusFilter === "all" || latestRun.status === statusFilter;
      const matchesType = fileTypeFilter === "all" || file.type === fileTypeFilter;
      return matchesSearch && matchesStatus && matchesType;
    });
  }, [fileTypeFilter, search, statusFilter]);

  useEffect(() => {
    if (!filteredFiles.length) return;

    const selectedFile =
      filteredFiles.find((file) => file.id === selectedFileId) ?? filteredFiles[0];

    if (selectedFile.id !== selectedFileId) {
      setSelectedFileId(selectedFile.id);
    }

    const selectedRun =
      selectedFile.runs.find((run) => run.id === selectedRunId) ?? selectedFile.runs[0];

    if (selectedRun.id !== selectedRunId) {
      setSelectedRunId(selectedRun.id);
    }

    const selectedChunk =
      selectedRun.chunks.find((chunk) => chunk.id === selectedChunkId) ?? selectedRun.chunks[0] ?? null;

    if (selectedChunk?.id !== selectedChunkId) {
      setSelectedChunkId(selectedChunk?.id ?? null);
    }
  }, [filteredFiles, selectedChunkId, selectedFileId, selectedRunId]);

  const selectedFile = filteredFiles.find((file) => file.id === selectedFileId) ?? null;
  const selectedRun = selectedFile?.runs.find((run) => run.id === selectedRunId) ?? selectedFile?.runs[0] ?? null;
  const selectedChunk = selectedRun?.chunks.find((chunk) => chunk.id === selectedChunkId) ?? selectedRun?.chunks[0] ?? null;
  const compareRun =
    selectedFile?.runs.find((run) => run.id === compareRunId) ?? null;
  const normalizedDocumentSearch = documentSearch.trim().toLowerCase();
  const documentMatches = useMemo(() => {
    if (!selectedRun || !normalizedDocumentSearch) return [];

    return selectedRun.chunks.filter((chunk) => {
      const haystack = [
        chunk.section,
        chunk.type,
        chunk.coordinates,
        chunk.displayText,
        chunk.fullText,
        chunk.vectorText,
      ]
        .join("\n")
        .toLowerCase();

      return haystack.includes(normalizedDocumentSearch);
    });
  }, [normalizedDocumentSearch, selectedRun]);
  const documentMatchIds = useMemo(
    () => new Set(documentMatches.map((chunk) => chunk.id)),
    [documentMatches],
  );
  const filteredChunks = useMemo(
    () =>
      selectedRun
        ? normalizedDocumentSearch
          ? selectedRun.chunks.filter((chunk) => documentMatchIds.has(chunk.id))
          : selectedRun.chunks
        : [],
    [documentMatchIds, normalizedDocumentSearch, selectedRun],
  );
  const currentMatchIndex = documentMatches.findIndex((chunk) => chunk.id === selectedChunk?.id);

  useEffect(() => {
    writeFilesUrlState({
      fileId: selectedFileId,
      runId: selectedRunId,
      chunkId: selectedChunkId,
      tab: selectedTab,
      search,
      documentSearch,
      status: statusFilter,
      fileType: fileTypeFilter,
      compareRunId,
    });
  }, [
    compareRunId,
    documentSearch,
    fileTypeFilter,
    search,
    selectedChunkId,
    selectedFileId,
    selectedRunId,
    selectedTab,
    statusFilter,
  ]);

  useEffect(() => {
    if (!normalizedDocumentSearch || !documentMatches.length) return;
    if (selectedChunkId && documentMatchIds.has(selectedChunkId)) return;
    setSelectedChunkId(documentMatches[0].id);
  }, [documentMatchIds, documentMatches, normalizedDocumentSearch, selectedChunkId]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!selectedRun || !selectedChunk) return;
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
        return;
      }

      const currentIndex = selectedRun.chunks.findIndex((chunk) => chunk.id === selectedChunk.id);
      if (event.key === "ArrowDown" && currentIndex < selectedRun.chunks.length - 1) {
        setSelectedChunkId(selectedRun.chunks[currentIndex + 1].id);
      }
      if (event.key === "ArrowUp" && currentIndex > 0) {
        setSelectedChunkId(selectedRun.chunks[currentIndex - 1].id);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedChunk, selectedRun]);

  const currentChunkComments = comments.filter(
    (comment) =>
      comment.fileId === selectedFile?.id &&
      comment.runId === selectedRun?.id &&
      comment.objectId === selectedChunk?.id,
  );

  const handleSaveReviewer = async () => {
    if (!reviewerDraft.trim()) return;
    await setReviewerName(reviewerDraft.trim());
    setReviewerNameState(reviewerDraft.trim());
    setNeedsReviewerModal(false);
  };

  const handleAddComment = async () => {
    if (!selectedFile || !selectedRun || !selectedChunk || !reviewerName || !commentDraft.text.trim()) {
      return;
    }

    const now = new Date().toISOString();
    const nextComment: ReviewComment = {
      id: crypto.randomUUID(),
      verdict: commentDraft.verdict,
      categories: commentDraft.categories
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean),
      text: commentDraft.text.trim(),
      quote: commentDraft.quote.trim() || undefined,
      reviewerName,
      createdAt: now,
      updatedAt: now,
      state: "open",
      environment: window.location.origin,
      fileId: selectedFile.id,
      runId: selectedRun.id,
      objectType: "chunk",
      objectId: selectedChunk.id,
      contentSignature: selectedChunk.contentSignature,
      ordinal: selectedChunk.ordinal,
      coordinates: selectedChunk.coordinates,
      source: "human",
    };

    await upsertComment(nextComment);
    setComments((prev) => [nextComment, ...prev]);
    setCommentDraft({ verdict: "question", categories: "", text: "", quote: "" });
  };

  const handleToggleCommentState = async (comment: ReviewComment) => {
    const updatedComment: ReviewComment = {
      ...comment,
      state: comment.state === "open" ? "reviewed" : "open",
      updatedAt: new Date().toISOString(),
    };

    await upsertComment(updatedComment);
    setComments((prev) => prev.map((item) => (item.id === comment.id ? updatedComment : item)));
  };

  const handleDeleteComment = async (commentId: string) => {
    await deleteComment(commentId);
    setComments((prev) => prev.filter((comment) => comment.id !== commentId));
  };

  const handleClearComments = async () => {
    await clearAllComments();
    setComments([]);
  };

  const handleImportFinding = async () => {
    if (!selectedFile || !selectedRun || !selectedChunk || !reviewerName || !selectedChunk.findings.length) {
      return;
    }

    const now = new Date().toISOString();
    const importedComment: ReviewComment = {
      id: crypto.randomUUID(),
      verdict: "problem",
      categories: ["граница чанка"],
      text: selectedChunk.findings[0],
      quote: simpleMarkdown(selectedChunk.displayText).replace(/\n+/g, " ").slice(0, 160),
      reviewerName,
      createdAt: now,
      updatedAt: now,
      state: "open",
      environment: window.location.origin,
      fileId: selectedFile.id,
      runId: selectedRun.id,
      objectType: "chunk",
      objectId: selectedChunk.id,
      contentSignature: selectedChunk.contentSignature,
      ordinal: selectedChunk.ordinal,
      coordinates: selectedChunk.coordinates,
      source: "agent",
    };

    await upsertComment(importedComment);
    setComments((prev) => [importedComment, ...prev]);
  };

  const handleCopy = async (value: string) => {
    await copyText(value);
  };

  const handleJumpToMatch = (direction: "next" | "prev") => {
    if (!documentMatches.length) return;

    const currentIndex = documentMatches.findIndex((chunk) => chunk.id === selectedChunkId);
    const startIndex = currentIndex === -1 ? 0 : currentIndex;
    const nextIndex =
      direction === "next"
        ? (startIndex + 1) % documentMatches.length
        : (startIndex - 1 + documentMatches.length) % documentMatches.length;

    setSelectedChunkId(documentMatches[nextIndex].id);
  };

  const renderHighlightedText = (text: string) => {
    if (!normalizedDocumentSearch) return text;

    const lowerText = text.toLowerCase();
    const parts: ReactNode[] = [];
    let startIndex = 0;
    let matchIndex = lowerText.indexOf(normalizedDocumentSearch);

    while (matchIndex !== -1) {
      if (matchIndex > startIndex) {
        parts.push(text.slice(startIndex, matchIndex));
      }

      const endIndex = matchIndex + normalizedDocumentSearch.length;
      parts.push(
        <mark key={`${matchIndex}-${endIndex}`} className={styles.searchHighlight}>
          {text.slice(matchIndex, endIndex)}
        </mark>,
      );

      startIndex = endIndex;
      matchIndex = lowerText.indexOf(normalizedDocumentSearch, endIndex);
    }

    if (startIndex < text.length) {
      parts.push(text.slice(startIndex));
    }

    return parts.length ? parts : text;
  };

  const renderPayloadInspector = () => {
    if (!selectedRun || !selectedChunk) return null;

    const tablePayloads = selectedRun.tables.filter((table) =>
      selectedChunk.payloads.some((payload) => payload.id === table.id),
    );
    const imagePayloads = selectedRun.images.filter((image) =>
      selectedChunk.payloads.some((payload) => payload.id === image.id),
    );
    const transcriptPayloads = selectedRun.transcripts.filter((transcript) =>
      selectedChunk.payloads.some((payload) => payload.id === transcript.id),
    );

    return (
      <div className={styles.payloadStack}>
        {tablePayloads.map((table) => (
          <TablePayloadCard key={table.id} payload={table} />
        ))}
        {imagePayloads.map((image) => (
          <ImagePayloadCard key={image.id} payload={image} />
        ))}
        {transcriptPayloads.map((transcript) => (
          <TranscriptPayloadCard key={transcript.id} payload={transcript} />
        ))}
        {!tablePayloads.length && !imagePayloads.length && !transcriptPayloads.length ? (
          <div className={styles.emptyBlock}>У этого чанка нет связанных payload.</div>
        ) : null}
      </div>
    );
  };

  const formatCommentSource = (comment: ReviewComment) =>
    comment.source === "agent" ? "agent" : "manual";

  const formatCommentMeta = (comment: ReviewComment) => {
    const parts = [
      comment.objectId,
      selectedRun?.pipeline ?? selectedFile?.pipeline ?? "pipeline",
      new Date(comment.updatedAt).toLocaleString("ru-RU"),
    ];

    return parts.join(" · ");
  };

  const renderInspectorContent = () => {
    if (!selectedChunk) {
      return <div className={styles.emptyBlock}>Выберите чанк, чтобы открыть инспектор.</div>;
    }

    if (selectedTab === "payloads") return renderPayloadInspector();
    if (selectedTab === "metadata") {
      return (
        <div className={styles.definitionList}>
          {Object.entries(selectedChunk.metadata).map(([key, value]) => (
            <div key={key} className={styles.definitionRow}>
              <span>{key}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      );
    }

    if (selectedTab === "diagnostics") {
      return (
        <div className={styles.diagnosticsList}>
          {selectedChunk.diagnostics.map((diagnostic) => (
            <div key={`${diagnostic.code}-${diagnostic.message}`} className={styles.diagnosticCard}>
              <span className={`${styles.diagnosticBadge} ${styles[diagnostic.severity]}`}>
                {diagnostic.severity}
              </span>
              <div>
                <strong>{diagnostic.code}</strong>
                <p>{diagnostic.message}</p>
              </div>
            </div>
          ))}
        </div>
      );
    }

    const currentText = getTextByTab(selectedChunk, selectedTab);
    const diffRightText =
      diffTarget === "none" ? "" : getTextByTab(selectedChunk, diffTarget);
    const diffRows = diffTarget === "none" ? [] : makeLineDiff(currentText, diffRightText);

    return (
      <div className={styles.textInspector}>
        <div className={styles.inspectorToolbar}>
          <div className={styles.textModeSwitch}>
            <button
              className={`${styles.modeButton} ${textMode === "rendered" ? styles.modeButtonActive : ""}`}
              onClick={() => setTextMode("rendered")}
              type="button"
            >
              Rendered
            </button>
            <button
              className={`${styles.modeButton} ${textMode === "raw" ? styles.modeButtonActive : ""}`}
              onClick={() => setTextMode("raw")}
              type="button"
            >
              Raw
            </button>
          </div>
          <button className={styles.secondaryButton} onClick={() => void handleCopy(currentText)} type="button">
            <Copy size={14} />
            <span>Копировать</span>
          </button>
        </div>
        <div className={styles.inspectorToolbar}>
          <div className={styles.toolbarGroup}>
            <select
              className={styles.select}
              value={diffTarget}
              onChange={(event) => setDiffTarget(event.target.value as typeof diffTarget)}
            >
              <option value="none">Без diff</option>
              <option value="display">Отображение</option>
              <option value="fulltext">Полный текст</option>
              <option value="vectortext">Векторный текст</option>
            </select>
            {diffTarget !== "none" ? (
              <select
                className={styles.select}
                value={diffMode}
                onChange={(event) => setDiffMode(event.target.value as typeof diffMode)}
              >
                <option value="side-by-side">Две колонки</option>
                <option value="unified">Единый вид</option>
              </select>
            ) : null}
          </div>
        </div>

        <div className={styles.textMetaRow}>
          <span>{selectedChunk.charCount} символов</span>
          <span>{selectedChunk.tokenCount} токенов</span>
          <span>{selectedChunk.hash}</span>
          <span>{selectedChunk.coordinates}</span>
        </div>

        {diffTarget === "none" ? (
          <div className={styles.textCard}>
            <pre className={styles.preformattedText}>
              {renderHighlightedText(textMode === "raw" ? currentText : simpleMarkdown(currentText))}
            </pre>
          </div>
        ) : diffMode === "side-by-side" ? (
          <div className={styles.diffColumns}>
            <div className={styles.diffColumn}>
              <div className={styles.diffLabel}>{selectedTab}</div>
              {diffRows.map((row, index) => (
                <pre key={`left-${index}`} className={`${styles.diffRow} ${row.changed ? styles.diffChanged : ""}`}>
                  {renderHighlightedText(row.left || " ")}
                </pre>
              ))}
            </div>
            <div className={styles.diffColumn}>
              <div className={styles.diffLabel}>{diffTarget}</div>
              {diffRows.map((row, index) => (
                <pre key={`right-${index}`} className={`${styles.diffRow} ${row.changed ? styles.diffChanged : ""}`}>
                  {renderHighlightedText(row.right || " ")}
                </pre>
              ))}
            </div>
          </div>
        ) : (
          <div className={styles.textCard}>
            {diffRows.map((row, index) => (
              <pre key={`unified-${index}`} className={`${styles.diffRow} ${row.changed ? styles.diffChanged : ""}`}>
                {renderHighlightedText(
                  row.left === row.right
                    ? `  ${row.left}`
                    : `- ${row.left || " "}\n+ ${row.right || " "}`,
                )}
              </pre>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={styles.page}>
      <header className={styles.topbar}>
        <div className={styles.topbarLeft}>
          <div>
            <h1 className={styles.title}>Lore Files Review</h1>
          </div>
        </div>
      </header>

      <div className={styles.layout}>
        <aside className={styles.leftPanel}>
          <div className={styles.panelHeader}>
            <h2>Файлы</h2>
            <span>{filteredFiles.length}</span>
          </div>

          <div className={styles.filtersCard}>
            <label className={styles.searchField}>
              <Search size={15} />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Найти файл"
              />
            </label>
            <div className={styles.filterGrid}>
              <label>
                <span>Статус</span>
                <select className={styles.select} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  <option value="all">Все</option>
                  <option value="success">Успешно</option>
                  <option value="active">В обработке</option>
                  <option value="failed">Ошибка</option>
                  <option value="skipped">Пропущено</option>
                </select>
              </label>
              <label>
                <span>Тип</span>
                <select className={styles.select} value={fileTypeFilter} onChange={(event) => setFileTypeFilter(event.target.value)}>
                  <option value="all">Все</option>
                  <option value="pdf">pdf</option>
                  <option value="xlsx">xlsx</option>
                  <option value="audio">audio</option>
                </select>
              </label>
            </div>
          </div>

          <div className={styles.fileList}>
            {filteredFiles.map((file) => {
              const stats = deriveFileStats(file, comments);

              return (
                <button
                  key={file.id}
                  className={`${styles.fileCard} ${file.id === selectedFile?.id ? styles.fileCardActive : ""}`}
                  onClick={() => {
                    setSelectedFileId(file.id);
                    setSelectedRunId(file.runs[0]?.id ?? null);
                    setSelectedChunkId(file.runs[0]?.chunks[0]?.id ?? null);
                  }}
                  type="button"
                >
                  <div className={styles.fileCardHeader}>
                    <div>
                      <strong>{file.name}</strong>
                      <span>{file.type.toUpperCase()} · {file.pipeline}</span>
                    </div>
                  </div>
                  <div className={styles.fileMeta}>
                    <span>{formatRunTime(stats.latestRun.processedAt)}</span>
                    <span className={`${styles.statusBadge} ${getRunSeverity(stats.latestRun.status)}`}>
                      {formatStatus(stats.latestRun.status)}
                    </span>
                  </div>
                </button>
              );
            })}

            {!filteredFiles.length ? <div className={styles.emptyBlock}>По фильтрам ничего не найдено.</div> : null}
          </div>
        </aside>

        <section className={styles.centerPanel}>
          {selectedFile && selectedRun ? (
            <>
              <div className={styles.panelHeaderLarge}>
                <div>
                  <h2>{selectedFile.name}</h2>
                  <div className={styles.headerMeta}>
                    <span>{selectedFile.type.toUpperCase()}</span>
                  </div>
                  <div className={styles.runActions}>
                    <select className={styles.select} value={selectedRun.id} onChange={(event) => setSelectedRunId(event.target.value)}>
                      {selectedFile.runs.map((run) => (
                        <option key={run.id} value={run.id}>
                          {run.label}
                        </option>
                      ))}
                    </select>
                    <button
                      className={styles.secondaryButton}
                      type="button"
                      onClick={() => {
                        if (compareRunId) {
                          setCompareRunId(null);
                          return;
                        }

                        const fallbackRun =
                          selectedFile.runs.find((run) => run.id !== selectedRun.id) ?? null;
                        setCompareRunId(fallbackRun?.id ?? null);
                      }}
                    >
                      {compareRunId ? "Убрать сравнение" : "Сравнить"}
                    </button>
                  </div>
                </div>
              </div>

              <div className={styles.runBannerRow}>
                <div className={styles.runMetric}>
                  <span className={styles.runMetricLabel}>Чанки</span>
                  <strong>{selectedRun.chunks.length}</strong>
                </div>
                <div className={styles.runMetric}>
                  <span className={styles.runMetricLabel}>Связанные данные</span>
                  <strong>{selectedRun.tables.length + selectedRun.images.length + selectedRun.transcripts.length}</strong>
                </div>
                <div className={styles.runMetric}>
                  <span className={styles.runMetricLabel}>Диагностика</span>
                  <strong>{selectedRun.chunks.reduce((count, chunk) => count + chunk.diagnostics.length, 0)}</strong>
                </div>
                <div className={styles.runMetric}>
                  <span className={styles.runMetricLabel}>Замечания</span>
                  <strong>{selectedRun.chunks.reduce((count, chunk) => count + chunk.findings.length, 0)}</strong>
                </div>
              </div>

              {compareRun ? (
                <div className={styles.compareCard}>
                  <div className={styles.compareHeader}>
                    <strong>Сравнение запусков</strong>
                    <span>{selectedRun.label} ↔ {compareRun.label}</span>
                  </div>
                  <div className={styles.compareGrid}>
                    <div>Добавлено: {Math.max(0, selectedRun.chunks.length - compareRun.chunks.length)}</div>
                    <div>Удалено: {Math.max(0, compareRun.chunks.length - selectedRun.chunks.length)}</div>
                    <div>Изменено: {selectedRun.chunks.filter((chunk, index) => compareRun.chunks[index]?.hash !== chunk.hash).length}</div>
                    <div>Неизменено: {selectedRun.chunks.filter((chunk, index) => compareRun.chunks[index]?.hash === chunk.hash).length}</div>
                  </div>
                </div>
              ) : null}

              <div className={styles.documentSearchRow}>
                <label className={styles.searchField}>
                  <Search size={15} />
                  <input
                    value={documentSearch}
                    onChange={(event) => setDocumentSearch(event.target.value)}
                    placeholder="Поиск по документу"
                  />
                </label>
                <div className={`${styles.textModeSwitch} ${styles.metaModeSwitch}`}>
                  <button
                    className={`${styles.modeButton} ${
                      isChunkMetaVisible ? styles.modeButtonActive : ""
                    }`}
                    onClick={() => setIsChunkMetaVisible(true)}
                    type="button"
                    aria-label="Показать информацию чанков"
                    title="Показать информацию"
                  >
                    <ListTree size={14} />
                  </button>
                  <button
                    className={`${styles.modeButton} ${
                      !isChunkMetaVisible ? styles.modeButtonActive : ""
                    }`}
                    onClick={() => setIsChunkMetaVisible(false)}
                    type="button"
                    aria-label="Скрыть информацию чанков"
                    title="Скрыть информацию"
                  >
                    <ListCollapse size={14} />
                  </button>
                </div>
                <div className={styles.documentSearchMeta}>
                  {documentSearch.trim() ? (
                    <>
                      <span>
                        {documentMatches.length
                          ? `${Math.max(currentMatchIndex, 0) + 1} из ${documentMatches.length}`
                          : "0 совпадений"}
                      </span>
                      <button
                        className={styles.secondaryButton}
                        onClick={() => handleJumpToMatch("prev")}
                        type="button"
                        disabled={!documentMatches.length}
                      >
                        <ChevronLeft size={14} />
                      </button>
                      <button
                        className={styles.secondaryButton}
                        onClick={() => handleJumpToMatch("next")}
                        type="button"
                        disabled={!documentMatches.length}
                      >
                        <ChevronRight size={14} />
                      </button>
                    </>
                  ) : null}
                </div>
              </div>

              <div className={styles.chunkList}>
                {filteredChunks.map((chunk) => {
                  const cardContent = getChunkCardContent(chunk);
                  const attachmentPreview = getChunkAttachmentPreview(selectedRun, chunk);
                  const isImageCard = attachmentPreview?.kind === "image";

                  return (
                    <button
                      key={chunk.id}
                      className={`${styles.chunkCard} ${selectedChunk?.id === chunk.id ? styles.chunkCardActive : ""}`}
                      onClick={() => setSelectedChunkId(chunk.id)}
                      type="button"
                    >
                      {isChunkMetaVisible ? (
                        <div className={styles.chunkMeta}>
                          <span>{formatChunkMetaLabel(chunk)}</span>
                        </div>
                      ) : null}
                      <strong className={styles.chunkTitle}>
                        {renderHighlightedText(isImageCard ? attachmentPreview.image.title : cardContent.title)}
                      </strong>
                      {attachmentPreview?.kind === "table" ? (
                        <div className={styles.chunkTablePreview}>
                          <table>
                            <thead>
                              <tr>
                                {attachmentPreview.table.schema.slice(0, 3).map((column) => (
                                  <th key={column.name}>{column.name}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {attachmentPreview.table.samples.slice(0, 2).map((row, rowIndex) => (
                                <tr key={rowIndex}>
                                  {attachmentPreview.table.schema.slice(0, 3).map((column) => (
                                    <td key={column.name}>{String(row[column.name] ?? "—")}</td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : null}
                      {isImageCard ? (
                        <div className={styles.assetCard}>
                          <div className={styles.assetPreviewFrame}>
                            <div className={styles.assetPreviewCanvas} aria-hidden="true">
                              <div className={styles.assetPreviewBeam} />
                              <div className={styles.assetPreviewSun} />
                              <div className={styles.assetPreviewHillLarge} />
                              <div className={styles.assetPreviewHillSmall} />
                              <div className={styles.assetPreviewLabel}>
                                Заявка -&gt; Руководитель -&gt; HR -&gt; Активация
                              </div>
                            </div>
                          </div>
                          <div className={styles.assetCardFooter}>
                            <span>
                              {attachmentPreview.image.hash} · {attachmentPreview.image.mimeType} · {attachmentPreview.image.fileSize}
                            </span>
                          </div>
                        </div>
                      ) : null}
                      {isImageCard ? (
                        <p className={styles.chunkPreview}>
                          {renderHighlightedText(attachmentPreview.image.description)}
                        </p>
                      ) : null}
                      {cardContent.preview && !isImageCard ? (
                        <p className={styles.chunkPreview}>{renderHighlightedText(cardContent.preview)}</p>
                      ) : null}
                    </button>
                  );
                })}

                {documentSearch.trim() && !filteredChunks.length ? (
                  <div className={styles.emptyBlock}>По этому документу ничего не найдено.</div>
                ) : null}
              </div>
            </>
          ) : (
            <div className={styles.emptyState}>Файл или запуск не найден.</div>
          )}
        </section>

        <aside className={styles.rightPanel}>
          {selectedChunk ? (
            <>
              <div className={styles.panelHeaderLarge}>
                <div>
                  <h2>Чанк #{selectedChunk.ordinal}</h2>
                  <div className={styles.headerMeta}>
                    <span>{selectedChunk.section}</span>
                    <span>{selectedChunk.contentSignature}</span>
                  </div>
                </div>
                <button
                  className={styles.secondaryButton}
                  onClick={() => setIsReviewDrawerOpen(true)}
                  type="button"
                >
                  <MessageSquarePlus size={14} />
                  <span>Комментарий</span>
                </button>
              </div>

              <div className={styles.tabs}>
                <select
                  className={`${styles.select} ${styles.tabSelect}`}
                  value={selectedTab}
                  onChange={(event) => setSelectedTab(event.target.value as InspectorTab)}
                  aria-label="Выбор раздела инспектора"
                >
                  {inspectorTabs.map((tab) => (
                    <option key={tab.id} value={tab.id}>
                      {tab.label}
                    </option>
                  ))}
                </select>
              </div>

              {renderInspectorContent()}
            </>
          ) : (
            <div className={styles.emptyState}>Выберите чанк справа, чтобы открыть данные.</div>
          )}
        </aside>
      </div>

      {isReviewDrawerOpen ? (
        <div className={styles.drawerLayer} onClick={() => setIsReviewDrawerOpen(false)}>
          <aside
            className={styles.reviewDrawer}
            onClick={(event) => event.stopPropagation()}
            aria-label="Локальное ревью"
          >
            <div className={styles.drawerHeader}>
              <div>
                <h2>Локальное ревью</h2>
                <p>{currentChunkComments.length} записей</p>
              </div>
              <button
                className={styles.drawerClose}
                onClick={() => setIsReviewDrawerOpen(false)}
                type="button"
                aria-label="Закрыть ревью"
              >
                <X size={16} />
              </button>
            </div>

            <div className={styles.drawerBody}>
              <div className={styles.commentForm}>
                <div className={styles.commentGrid}>
                  <label>
                    <span>Вердикт</span>
                    <select
                      className={styles.select}
                      value={commentDraft.verdict}
                      onChange={(event) =>
                        setCommentDraft((prev) => ({
                          ...prev,
                          verdict: event.target.value as ReviewVerdict,
                        }))
                      }
                    >
                      <option value="OK">OK</option>
                      <option value="problem">Проблема</option>
                      <option value="question">Вопрос</option>
                    </select>
                  </label>
                  <label>
                    <span>Категория</span>
                    <input
                      list="review-categories"
                      value={commentDraft.categories}
                      onChange={(event) =>
                        setCommentDraft((prev) => ({ ...prev, categories: event.target.value }))
                      }
                      placeholder="Граница чанка"
                    />
                    <datalist id="review-categories">
                      {commentCategories.map((category) => (
                        <option key={category} value={category} />
                      ))}
                    </datalist>
                  </label>
                </div>
                <label>
                  <span>Цитата</span>
                  <input
                    value={commentDraft.quote}
                    onChange={(event) =>
                      setCommentDraft((prev) => ({ ...prev, quote: event.target.value }))
                    }
                    placeholder="Необязательно"
                  />
                </label>
                <label>
                  <span>Комментарий</span>
                  <textarea
                    value={commentDraft.text}
                    onChange={(event) =>
                      setCommentDraft((prev) => ({ ...prev, text: event.target.value }))
                    }
                    rows={4}
                    placeholder="Что нужно проверить или исправить?"
                  />
                </label>
                <div className={styles.drawerActions}>
                  <button
                    className={styles.secondaryButton}
                    onClick={() => void handleImportFinding()}
                    type="button"
                    disabled={!selectedChunk?.findings.length}
                  >
                    Импорт AI finding
                  </button>
                  <button className={styles.primaryButton} onClick={() => void handleAddComment()} type="button">
                    Сохранить
                  </button>
                </div>
              </div>

              <section className={styles.drawerCommentsSection}>
                <div className={styles.drawerSectionHeader}>
                  <h3>Все комментарии</h3>
                  <div className={styles.toolbarGroup}>
                    <button className={styles.ghostButton} onClick={handleClearComments} type="button">
                      Очистить
                    </button>
                  </div>
                </div>
                <div className={styles.commentList}>
                  {currentChunkComments.map((comment) => (
                    <article key={comment.id} className={styles.commentCard}>
                      <div className={styles.commentLead}>
                        <span className={styles.commentLeadItem}>{comment.verdict.toLowerCase()}</span>
                        {comment.categories[0] ? (
                          <span className={styles.commentLeadItem}>{comment.categories[0]}</span>
                        ) : null}
                        <span className={styles.commentLeadItem}>{formatCommentSource(comment)}</span>
                      </div>
                      {comment.quote ? <blockquote>&ldquo;{comment.quote}&rdquo;</blockquote> : null}
                      <p>{comment.text}</p>
                      <div className={styles.commentMetaLine}>{formatCommentMeta(comment)}</div>
                      <div className={styles.commentFooter}>
                        <div className={styles.toolbarGroup}>
                          <button className={styles.ghostButton} onClick={() => void handleToggleCommentState(comment)} type="button">
                            {comment.state === "open" ? "Отметить просмотренным" : "Переоткрыть"}
                          </button>
                          <button className={styles.ghostButtonDanger} onClick={() => void handleDeleteComment(comment.id)} type="button">
                            Удалить
                          </button>
                        </div>
                      </div>
                    </article>
                  ))}
                  {!currentChunkComments.length ? (
                    <div className={styles.drawerEmpty}>
                      <strong>Комментариев пока нет</strong>
                      <p>Оставьте ревью к выбранному чанку или импортируйте AI finding.</p>
                    </div>
                  ) : null}
                </div>
              </section>
            </div>
          </aside>
        </div>
      ) : null}

      {needsReviewerModal ? (
        <div className={styles.modalOverlay}>
          <div className={styles.modal}>
            <h2>Имя ревьюера</h2>
            <p>При первом открытии укажите имя, под которым будут сохраняться локальные комментарии.</p>
            <input
              value={reviewerDraft}
              onChange={(event) => setReviewerDraft(event.target.value)}
              placeholder="Например, Aleksey"
              autoFocus
            />
            <button className={styles.primaryButton} onClick={() => void handleSaveReviewer()} type="button">
              Сохранить
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function TablePayloadCard({ payload }: { payload: FileTablePayload }) {
  return (
    <section className={styles.payloadCard}>
      <div className={styles.payloadHeader}>
        <div className={styles.payloadTitle}>
          <Table2 size={16} />
          <strong>Таблица</strong>
        </div>
        <span>{payload.coordinates}</span>
      </div>
      <p>{payload.summary}</p>
      <div className={styles.metricsRow}>
        <span>{payload.rowCount} строк</span>
        <span>{payload.columnCount} колонок</span>
        <span>{payload.contentId}</span>
      </div>
      <div className={styles.tablePreview}>
        <table>
          <thead>
            <tr>
              {payload.schema.map((column) => (
                <th key={column.name}>
                  {column.name}
                  <small>{column.type}</small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {payload.samples.map((row, index) => (
              <tr key={index}>
                {payload.schema.map((column) => (
                  <td key={column.name}>{String(row[column.name] ?? "NULL")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ImagePayloadCard({ payload }: { payload: FileImagePayload }) {
  return (
    <section className={styles.payloadCard}>
      <div className={styles.payloadHeader}>
        <div className={styles.payloadTitle}>
          <ImageIcon size={16} />
          <strong>{payload.title}</strong>
        </div>
        <span>{payload.coordinates}</span>
      </div>
      <div className={styles.imagePreview}>
        {payload.unavailable ? (
          <div className={styles.imageUnavailable}>
            <FileWarning size={18} />
            <span>Объект недоступен</span>
          </div>
        ) : (
          <div className={styles.imagePlaceholder}>Предпросмотр</div>
        )}
      </div>
      <p>{payload.description}</p>
      <div className={styles.metricsRow}>
        <span>{payload.mimeType}</span>
        <span>{payload.dimensions}</span>
        <span>{payload.fileSize}</span>
      </div>
    </section>
  );
}

function TranscriptPayloadCard({ payload }: { payload: FileTranscriptPayload }) {
  return (
    <section className={styles.payloadCard}>
      <div className={styles.payloadHeader}>
        <div className={styles.payloadTitle}>
          <Rows3 size={16} />
          <strong>{payload.title}</strong>
        </div>
        <span>{payload.blocks.length} блоков</span>
      </div>
      <div className={styles.transcriptList}>
        {payload.blocks.map((block) => (
          <div key={block.id} className={styles.transcriptBlock}>
            <strong>{block.speaker}</strong>
            <span>{block.timeRange}</span>
            <p>{block.display}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
