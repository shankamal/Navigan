// A non-sensitive, tab-local presentation flag; never an authentication decision.
const KEY = "navigan.lifecycle-intro.pending.v1";
export function markLifecycleIntroPending(): void {
  try {
    window.sessionStorage.setItem(KEY, "1");
  } catch {
    /* Storage restrictions must not block sign-in. */
  }
}
export function hasPendingLifecycleIntro(): boolean {
  try {
    return window.sessionStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}
export function clearPendingLifecycleIntro(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    /* Continue safely without storage. */
  }
}
