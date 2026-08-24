// Debug logging that ships silent: several call sites dump full API payloads
// (recommendations, preferences) which is useful in development but noise —
// and a needless data surface — in production consoles. Errors and warnings
// keep using console.error / console.warn directly.
export const debugLog: typeof console.log = import.meta.env.DEV
  ? console.log.bind(console)
  : () => {}
