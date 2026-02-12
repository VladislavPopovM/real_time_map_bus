export class BusStore {
  buses = new Map(); 
  socket = null;
  isConnected = $state(false);
  count = $state(0);
  ups = $state(0); // Updates per second

  constructor(url = 'ws://localhost:8000') {
    this._msgCount = 0;
    this._lastUpsUpdate = 0;
    this.connect(url);
  }

  connect(url) {
    this.socket = new WebSocket(url);
    this.socket.binaryType = 'arraybuffer';
    this.socket.onopen = () => { this.isConnected = true; };
    this.socket.onclose = () => {
      this.isConnected = false;
      setTimeout(() => this.connect(url), 2000);
    };
    this.socket.onmessage = (event) => { 
      this._msgCount++;
      this.handleBinaryMessage(event.data); 
      this.updateUps();
    };
  }

  updateUps() {
    const now = performance.now();
    if (now - this._lastUpsUpdate > 1000) {
      this.ups = this._msgCount;
      this._msgCount = 0;
      this._lastUpsUpdate = now;
    }
  }

  handleBinaryMessage(buffer) {
    if (!(buffer instanceof ArrayBuffer)) return;
    const data = new Float32Array(buffer);
    const now = performance.now();
    const seenIds = new Set();

    for (let i = 0; i < data.length; i += 4) {
      const id = data[i];
      const lat = data[i+1];
      const lng = data[i+2];
      const route = data[i+3];
      seenIds.add(id);

      if (this.buses.has(id)) {
        const bus = this.buses.get(id);
        const dist = Math.abs(bus.targetLat - lat) + Math.abs(bus.targetLng - lng);
        
        // Телепортация при больших прыжках
        if (dist > 0.05) {
          bus.curLat = lat; bus.curLng = lng;
          bus.startLat = lat; bus.startLng = lng;
        } else {
          // Мягкое переключение: начинаем с текущей позиции
          bus.startLat = bus.curLat || bus.startLat;
          bus.startLng = bus.curLng || bus.startLng;
        }
        
        bus.targetLat = lat;
        bus.targetLng = lng;
        bus.startTime = now;
      } else {
        this.buses.set(id, {
          id, route,
          curLat: lat, curLng: lng,
          startLat: lat, startLng: lng,
          targetLat: lat, targetLng: lng,
          startTime: now
        });
      }
    }

    if (Math.random() > 0.9) {
      for (const id of this.buses.keys()) {
        if (!seenIds.has(id)) this.buses.delete(id);
      }
    }
    this.count = this.buses.size;
  }
}

export const busStore = new BusStore();
