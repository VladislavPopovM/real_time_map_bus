export class BusStore {
  // Карта автобусов: id -> { id, route, curLat, curLng, startLat, startLng, targetLat, targetLng, startTime }
  buses = new Map(); 
  socket = null;
  isConnected = $state(false);
  count = $state(0);

  constructor(url = 'ws://localhost:8000') {
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
    this.socket.onmessage = (event) => { this.handleBinaryMessage(event.data); };
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
        // Если данные изменились — начинаем ПЛАВНЫЙ переход от текущей точки
        if (bus.targetLat !== lat || bus.targetLng !== lng) {
          bus.startLat = bus.curLat || bus.startLat;
          bus.startLng = bus.curLng || bus.startLng;
          bus.targetLat = lat;
          bus.targetLng = lng;
          bus.startTime = now;
        }
      } else {
        // Новый автобус: появляется мгновенно
        this.buses.set(id, {
          id, route,
          curLat: lat, curLng: lng,
          startLat: lat, startLng: lng,
          targetLat: lat, targetLng: lng,
          startTime: now
        });
      }
    }

    // Редкая очистка зомби (раз в 5 пакетов)
    if (Math.random() > 0.8) {
      for (const id of this.buses.keys()) {
        if (!seenIds.has(id)) this.buses.delete(id);
      }
    }
    this.count = this.buses.size;
  }
}

export const busStore = new BusStore();
