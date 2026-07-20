import type { ReviewComment } from "./types";

const DB_NAME = "lore-files-review";
const DB_VERSION = 1;
const COMMENT_STORE = "comments";
const SETTINGS_STORE = "settings";

const openDb = () =>
  new Promise<IDBDatabase>((resolve, reject) => {
    const request = window.indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = () => {
      const db = request.result;

      if (!db.objectStoreNames.contains(COMMENT_STORE)) {
        const comments = db.createObjectStore(COMMENT_STORE, { keyPath: "id" });
        comments.createIndex("byFile", "fileId", { unique: false });
      }

      if (!db.objectStoreNames.contains(SETTINGS_STORE)) {
        db.createObjectStore(SETTINGS_STORE, { keyPath: "key" });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

const withStore = async <T>(
  storeName: string,
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore, resolve: (value: T) => void, reject: (reason?: unknown) => void) => void,
) => {
  const db = await openDb();

  return new Promise<T>((resolve, reject) => {
    const tx = db.transaction(storeName, mode);
    const store = tx.objectStore(storeName);
    operation(store, resolve, reject);
    tx.oncomplete = () => db.close();
    tx.onerror = () => reject(tx.error);
  });
};

export const listComments = async (): Promise<ReviewComment[]> =>
  withStore(COMMENT_STORE, "readonly", (store, resolve, reject) => {
    const request = store.getAll();
    request.onsuccess = () => resolve((request.result as ReviewComment[]).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
    request.onerror = () => reject(request.error);
  });

export const upsertComment = async (comment: ReviewComment): Promise<void> =>
  withStore(COMMENT_STORE, "readwrite", (store, resolve, reject) => {
    const request = store.put(comment);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });

export const deleteComment = async (id: string): Promise<void> =>
  withStore(COMMENT_STORE, "readwrite", (store, resolve, reject) => {
    const request = store.delete(id);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });

export const clearAllComments = async (): Promise<void> =>
  withStore(COMMENT_STORE, "readwrite", (store, resolve, reject) => {
    const request = store.clear();
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });

export const getReviewerName = async (): Promise<string> =>
  withStore(SETTINGS_STORE, "readonly", (store, resolve, reject) => {
    const request = store.get("reviewerName");
    request.onsuccess = () => resolve((request.result?.value as string | undefined) ?? "");
    request.onerror = () => reject(request.error);
  });

export const setReviewerName = async (reviewerName: string): Promise<void> =>
  withStore(SETTINGS_STORE, "readwrite", (store, resolve, reject) => {
    const request = store.put({ key: "reviewerName", value: reviewerName });
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
