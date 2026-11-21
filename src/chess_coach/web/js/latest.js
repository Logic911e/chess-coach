// Latest-wins sequencing for overlapping async requests. Pure: no window/document.
// track(promise) resolves { value } for the newest request, { stale: true } for one that has been overtaken
// (whether it succeeded or failed), and rejects only when the newest request itself failed.
export function createLatest() {
  let seq = 0;
  return {
    begin() { seq += 1; return seq; },
    isLatest(token) { return token === seq; },
    async track(promise) {
      seq += 1;
      const mine = seq;
      try {
        const value = await promise;
        return mine === seq ? { value } : { stale: true };
      } catch (e) {
        if (mine !== seq) return { stale: true };
        throw e;
      }
    },
  };
}
