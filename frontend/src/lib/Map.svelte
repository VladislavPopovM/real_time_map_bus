<script>
  import { onMount } from 'svelte';
  import L from 'leaflet';
  import { busStore } from './busStore.svelte.js';

  let mapElement;
  let map;
  let zoom = $state(13); // Храним текущий зум
  const markers = new Map();

  // Динамическая иконка с масштабированием (Шаг: Адаптивность)
  const createBusIcon = (route, currentZoom) => {
    // Рассчитываем коэффициент масштаба относительно базового зума 13
    const scale = Math.max(0.5, Math.pow(1.3, currentZoom - 13));
    const baseSize = 30;
    const size = baseSize * scale;
    // Делаем шрифт пропорционально крупнее и жирнее
    const fontSize = 7; // В единицах viewBox (0-24)
    
    return L.divIcon({
      className: 'bus-icon',
      html: `
        <svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M4 16C4 17.1 4.9 18 6 18H18C19.1 18 20 17.1 20 16V6C20 4.9 19.1 4 18 4H6C4.9 4 4 4.9 4 6V16Z" fill="#3B82F6"/>
          <path d="M18 18V20H16V18H8V20H6V18" stroke="#1E40AF" stroke-width="2" stroke-linecap="round"/>
          <rect x="5" y="5" width="14" height="8" rx="1" fill="#93C5FD"/>
          <text x="12" y="11" 
                font-family="Arial, sans-serif" 
                font-size="${fontSize}" 
                font-weight="900" 
                fill="#1E3A8A" 
                text-anchor="middle" 
                dominant-baseline="middle"
                style="pointer-events: none;">${route}</text>
          <circle cx="8" cy="15" r="1.5" fill="#1E3A8A"/>
          <circle cx="16" cy="15" r="1.5" fill="#1E3A8A"/>
        </svg>
      `,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
      popupAnchor: [0, -size / 2]
    });
  };

  onMount(() => {
    const center = [55.751244, 37.618423];
    map = L.map(mapElement, { attributionControl: false }).setView(center, 13);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

    // Шаг 13: Отправляем координаты окна сервера при движении карты
    const sendBounds = () => {
      const bounds = map.getBounds();
      const southWest = bounds.getSouthWest();
      const northEast = bounds.getNorthEast();

      const message = {
        msgType: 'newBounds',
        data: {
          southWest: { lat: southWest.lat, lng: southWest.lng },
          northEast: { lat: northEast.lat, lng: northEast.lng }
        }
      };
      
      if (busStore.socket && busStore.socket.readyState === WebSocket.OPEN) {
        busStore.socket.send(JSON.stringify(message));
      }
    };

    map.on('moveend', sendBounds);
    
    // Отправляем начальные координаты сразу после загрузки
    setTimeout(sendBounds, 1000);

    return () => {
      map.off('moveend', sendBounds);
      map.remove();
    };
  });

  // Реактивный эффект: следим за изменениями в busStore.buses И зумом
  $effect(() => {
    if (!map) return;

    const currentBuses = busStore.buses;
    
    // 1. Обновляем или добавляем маркеры
    for (const [id, bus] of Object.entries(currentBuses)) {
      if (markers.has(id)) {
        const marker = markers.get(id);
        marker.setLatLng([bus.lat, bus.lng]);
        
        // ТОНКОСТЬ: Обновляем иконку ТОЛЬКО если зум изменился.
        // Leaflet хранит текущий зум в объекте маркера или мы можем проверить вручную.
        if (marker._lastZoom !== zoom) {
          marker.setIcon(createBusIcon(bus.route, zoom));
          marker._lastZoom = zoom;
        }
      } else {
        const icon = createBusIcon(bus.route, zoom);
        const marker = L.marker([bus.lat, bus.lng], { icon })
          .bindPopup(`Bus Route: ${bus.route}`)
          .addTo(map);
        marker._lastZoom = zoom;
        markers.set(id, marker);
      }
    }

    // 2. Удаляем старые маркеры
    const currentIds = new Set(Object.keys(currentBuses));
    for (const [id, marker] of markers.entries()) {
      if (!currentIds.has(id)) {
        map.removeLayer(marker);
        markers.delete(id);
      }
    }
  });
</script>

<div class="status-indicator" class:connected={busStore.isConnected}>
  {busStore.isConnected ? 'Connected' : 'Disconnected'}
</div>

<div bind:this={mapElement} class="map-container"></div>

<style>
  .map-container {
    height: 100vh; /* Fallback for older browsers */
    height: 100dvh; /* Modern dynamic viewport height */
    width: 100vw;
    position: absolute;
    top: 0;
    left: 0;
    z-index: 1;
  }

  .status-indicator {
    position: absolute;
    top: 10px;
    right: 10px;
    z-index: 1000;
    padding: 5px 10px;
    background: rgba(255, 0, 0, 0.7);
    color: white;
    border-radius: 4px;
    font-family: sans-serif;
    font-size: 12px;
    pointer-events: none;
  }

  .status-indicator.connected {
    background: rgba(0, 255, 0, 0.7);
    color: black;
  }

  /* Стили для иконки автобуса */
  :global(.bus-icon) {
    background: transparent;
    border: none;
    /* transition чуть дольше чем интервал обновления (0.1s), 
       чтобы сгладить сетевой джиттер */
    transition: transform 0.15s linear; 
  }
</style>
