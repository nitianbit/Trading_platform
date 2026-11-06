import { useEffect, useState } from "react";

// A clock is state, not a render-time side effect. It also lets stale data
// expire when an upstream feed stops producing renders.
export function useNow(enabled = true) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!enabled) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [enabled]);
  return now;
}
