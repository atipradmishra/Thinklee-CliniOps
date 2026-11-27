/* Browser-only scheduling. The server still authorizes every fresh-data request. */
(() => {
  const intervals = {minute: 60000, '5minutes': 300000, '15minutes': 900000,
    hourly: 3600000, daily: 86400000, weekly: 604800000};
  const labels = {manual: 'Manual', minute: 'Every minute', '5minutes': 'Every 5 minutes',
    '15minutes': 'Every 15 minutes', hourly: 'Hourly', daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly'};
  function nextRefresh(last, rate) {
    if (rate === 'monthly') {
      const next = new Date(last);
      const day = next.getUTCDate();
      next.setUTCDate(1);
      next.setUTCMonth(next.getUTCMonth() + 1);
      const finalDay = new Date(Date.UTC(next.getUTCFullYear(), next.getUTCMonth()+1, 0)).getUTCDate();
      next.setUTCDate(Math.min(day, finalDay));
      return next.getTime();
    }
    return intervals[rate] ? last + intervals[rate] : Infinity;
  }
  class WidgetRefreshScheduler {
    constructor({widgets, load, onStatus = () => {}, now = Date.now,
                 visible = () => !document.hidden && navigator.onLine !== false}) {
      this.widgets = widgets; this.load = load; this.onStatus = onStatus;
      this.now = now; this.visible = visible; this.states = new Map();
      this.timer = null; this.paused = false; this.ticking = false; this.stopped = false;
      this.wake = () => { void this.tick(); };
      this.leave = () => this.stop();
    }
    start() {
      if (this.timer !== null || this.paused) return;
      this.stopped = false;
      this.timer = setInterval(this.wake, 15000);
      document.addEventListener('visibilitychange', this.wake);
      window.addEventListener('online', this.wake);
      window.addEventListener('pagehide', this.leave);
      this.wake();
    }
    stop() {
      this.stopped = true;
      if (this.timer !== null) clearInterval(this.timer);
      this.timer = null;
      document.removeEventListener('visibilitychange', this.wake);
      window.removeEventListener('online', this.wake);
      window.removeEventListener('pagehide', this.leave);
    }
    pause() { this.paused = true; this.stop(); }
    state(widget) {
      if (!this.states.has(widget.id)) this.states.set(widget.id, {lastSuccess:null, retryAt:0, pending:null, failed:false});
      return this.states.get(widget.id);
    }
    refresh(widget) {
      const state = this.state(widget);
      if (state.pending) return state.pending;
      state.pending = Promise.resolve().then(() => this.load(widget)).then(ok => {
        state.failed = !ok;
        if (ok) { state.lastSuccess = this.now(); state.retryAt = 0; }
        else state.retryAt = this.now() + 300000;
        return Boolean(ok);
      }).catch(() => { state.failed = true; state.retryAt = this.now()+300000; return false; })
        .finally(() => { state.pending = null; this.onStatus(widget, state); });
      this.onStatus(widget, state);
      return state.pending;
    }
    async tick() {
      if (this.ticking || this.stopped || this.paused || !this.visible()) return;
      this.ticking = true;
      try {
        // Sequential requests avoid hitting every connected DB simultaneously.
        for (const widget of this.widgets()) {
          if (this.stopped || this.paused || !this.visible()) break;
          if (widget.is_active === false || !labels[widget.refresh_rate] || widget.refresh_rate === 'manual') continue;
          const state = this.state(widget);
          const due = state.failed ? state.retryAt : (state.lastSuccess === null ? 0 : nextRefresh(state.lastSuccess, widget.refresh_rate));
          if (!state.pending && this.now() >= Math.max(due, state.retryAt)) await this.refresh(widget);
        }
      } finally { this.ticking = false; }
    }
  }
  window.WidgetRefresh = {Scheduler: WidgetRefreshScheduler, nextRefresh, labels};
})();
