export class BusStore {
  // Используем руну $state для реактивности.
  // Храним автобусы как объект: { "busId": { lat, lng, route, ... } }
  buses = $state({});
  socket = null;
  isConnected = $state(false);

  constructor(url = 'ws://localhost:8000') {
    this.connect(url);
  }

  connect(url) {
    this.socket = new WebSocket(url);

    this.socket.onopen = () => {
      console.log('WS Connected');
      this.isConnected = true;
    };

    this.socket.onclose = () => {
      console.log('WS Disconnected');
      this.isConnected = false;
      // Простейший реконнект через 2 секунды
      setTimeout(() => this.connect(url), 2000);
    };

    this.socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handleMessage(data);
      } catch (e) {
        console.error('Failed to parse WS message:', e);
      }
    };
  }

  handleMessage(data) {
    if (data.msgType === 'Buses' && Array.isArray(data.buses)) {
      // Клонируем объект, чтобы Svelte гарантированно увидел изменения
      const newBuses = { ...this.buses };
      data.buses.forEach(bus => {
        newBuses[bus.busId] = bus;
      });
      this.buses = newBuses;
    }
  }
}

// Создаем синглтон (глобальный инстанс), если нужно одно подключение на все приложение
export const busStore = new BusStore();
