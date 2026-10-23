/** Keep a command's key after uncertain transport; clear only on confirmed success. */
const memory = new Map<string, string>();
export async function commandRequest<T>(path: string, values: Record<string, unknown>): Promise<T> {
 const fingerprint = JSON.stringify([path, values]);
 const storageKey = 'terra.pending-command.' + fingerprint;
 let key = memory.get(fingerprint);
 try { key ??= sessionStorage.getItem(storageKey) ?? undefined; } catch { /* Memory fallback. */ }
 key ??= crypto.randomUUID(); memory.set(fingerprint, key);
 try { sessionStorage.setItem(storageKey, key); } catch { /* Memory fallback. */ }
 const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...values, idempotency_key: key }) });
 const payload = await response.json();
 if (!response.ok || payload.error || !payload.data) throw new Error(payload.error?.message ?? `Terra returned HTTP ${response.status}.`);
 memory.delete(fingerprint);
 try { sessionStorage.removeItem(storageKey); } catch { /* Memory fallback. */ }
 return payload.data as T;
}

export function resetPendingCommands() { memory.clear(); }
