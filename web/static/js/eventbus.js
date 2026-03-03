/**
 * Client-side EventBus — mirrors core/event_bus.py pattern.
 * Singleton, supports wildcard "*" listeners.
 */
class EventBus {
  constructor() {
    this._listeners = new Map();  // event -> Set<callback>
    this._wildcard = new Set();
  }

  on(event, callback) {
    if (event === "*") {
      this._wildcard.add(callback);
    } else {
      if (!this._listeners.has(event)) {
        this._listeners.set(event, new Set());
      }
      this._listeners.get(event).add(callback);
    }
  }

  off(event, callback) {
    if (event === "*") {
      this._wildcard.delete(callback);
    } else {
      const set = this._listeners.get(event);
      if (set) set.delete(callback);
    }
  }

  emit(event, data) {
    // Specific listeners
    const set = this._listeners.get(event);
    if (set) {
      for (const cb of set) {
        try { cb(data); } catch (e) { console.error(`EventBus [${event}]:`, e); }
      }
    }
    // Wildcard listeners
    for (const cb of this._wildcard) {
      try { cb(event, data); } catch (e) { console.error(`EventBus [*]:`, e); }
    }
  }
}

// Singleton
const bus = new EventBus();
export default bus;
