import type { Reading } from "./types";

const DATABASE = "gridsense-edge-v1";
function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore("outbox", { keyPath: "event_id" });
      request.result.createObjectStore("snapshots");
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function run<T>(
  store: string,
  mode: IDBTransactionMode,
  operation: (objectStore: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction(store, mode);
      const request = operation(transaction.objectStore(store));
      transaction.oncomplete = () => resolve(request.result);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () =>
        reject(transaction.error || new Error("Storage transaction aborted"));
    });
  } finally {
    db.close();
  }
}

export const queueReading = (reading: Reading) =>
  run("outbox", "readwrite", (store) => store.add(reading));
export const pendingReadings = (): Promise<Reading[]> =>
  run("outbox", "readonly", (store) => store.getAll());
export const saveSnapshot = (key: string, value: unknown) =>
  run("snapshots", "readwrite", (store) => store.put(value, key));
export const loadSnapshot = <T>(key: string): Promise<T | undefined> =>
  run("snapshots", "readonly", (store) => store.get(key));

let flushing: Promise<number> | undefined;
export function flushReadings(
  token: string,
  sender: typeof fetch = fetch,
): Promise<number> {
  if (flushing) return flushing;
  flushing = (async () => {
    const readings = (await pendingReadings()).slice(0, 100);
    if (!readings.length) return 0;
    const response = await sender("/api/readings/batch", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Device-Token": token },
      body: JSON.stringify({ readings }),
    });
    if (!response.ok)
      throw new Error(
        `Upload rejected (${response.status}); readings remain queued.`,
      );
    const ack = await response.json();
    const identifiers = new Set<string>(ack.event_ids || []);
    if (
      identifiers.size !== readings.length ||
      readings.some((row) => !identifiers.has(row.event_id)) ||
      (ack.accepted || 0) + (ack.duplicates || 0) !== readings.length
    ) {
      throw new Error("Incomplete acknowledgement; readings remain queued.");
    }
    const db = await openDatabase();
    try {
      await new Promise<void>((resolve, reject) => {
        const transaction = db.transaction("outbox", "readwrite");
        readings.forEach((row) =>
          transaction.objectStore("outbox").delete(row.event_id),
        );
        transaction.oncomplete = () => resolve();
        transaction.onabort = transaction.onerror = () =>
          reject(transaction.error);
      });
    } finally {
      db.close();
    }
    return readings.length;
  })().finally(() => {
    flushing = undefined;
  });
  return flushing;
}
