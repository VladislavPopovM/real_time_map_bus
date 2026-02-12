<script>
  import { onMount } from 'svelte';
  import L from 'leaflet';
  import { busStore } from './busStore.svelte.js';

  let mapElement;
  let map;
  
  onMount(() => {
    map = L.map(mapElement, { 
      attributionControl: false,
      zoomControl: false,
      center: [55.751244, 37.618423],
      zoom: 13,
      preferCanvas: true
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(map);

    L.BusLayer = L.Layer.extend({
      onAdd: function(map) {
        this._map = map;
        this._canvas = L.DomUtil.create('canvas', 'leaflet-bus-layer');
        this._canvas.style.position = 'absolute';
        this._canvas.style.top = '0';
        this._canvas.style.left = '0';
        this._canvas.style.pointerEvents = 'none';
        this._canvas.style.zIndex = '999';
        map.getContainer().appendChild(this._canvas);
        this._ctx = this._canvas.getContext('2d', { alpha: true });
        
        map.on('move zoom viewreset', this._reset, this);
        this._reset();
        this._animate();
      },

      onRemove: function(map) {
        map.getContainer().removeChild(this._canvas);
        cancelAnimationFrame(this._requestId);
      },

      _reset: function() {
        const size = this._map.getSize();
        if (this._canvas.width !== size.x || this._canvas.height !== size.y) {
          this._canvas.width = size.x;
          this._canvas.height = size.y;
        }
      },

      _animate: function() {
        this._draw();
        this._requestId = requestAnimationFrame(this._animate.bind(this));
      },

      _draw: function() {
        if (!this._map) return;
        const ctx = this._ctx;
        const size = this._map.getSize();
        const now = performance.now();
        const duration = 200;

        ctx.clearRect(0, 0, size.x, size.y);
        
        const buses = busStore.buses;
        if (buses.size === 0) return;

        // Группируем по 10 цветам
        const groups = Array.from({length: 10}, () => []);

        for (const bus of buses.values()) {
          // 1. Интерполяция
          let t = (now - bus.startTime) / duration;
          if (t > 1) t = 1;
          
          const lat = bus.startLat + (bus.targetLat - bus.startLat) * t;
          const lng = bus.startLng + (bus.targetLng - bus.startLng) * t;
          bus.curLat = lat;
          bus.curLng = lng;

          // 2. Проекция (ContainerPoint гарантирует точность при движении)
          const point = this._map.latLngToContainerPoint([lat, lng]);

          if (point.x < -5 || point.y < -5 || point.x > size.x + 5 || point.y > size.y + 5) continue;

          groups[Math.floor(bus.route % 10)].push(point.x, point.y);
        }

        // 3. Отрисовка пачками
        ctx.lineWidth = 0.5;
        ctx.strokeStyle = "rgba(255,255,255,0.6)";
        
        groups.forEach((coords, i) => {
          if (coords.length === 0) return;
          ctx.beginPath();
          ctx.fillStyle = `hsl(${(i * 36) % 360}, 100%, 65%)`;
          for (let j = 0; j < coords.length; j += 2) {
            const x = coords[j];
            const y = coords[j+1];
            ctx.moveTo(x + 2.5, y);
            ctx.arc(x, y, 2.5, 0, Math.PI * 2);
          }
          ctx.fill();
          ctx.stroke();
        });
      }
    });

    map.addLayer(new L.BusLayer());

    const sendBounds = () => {
      const b = map.getBounds();
      const msg = {
        msgType: 'newBounds',
        data: {
          southWest: { lat: b.getSouthWest().lat, lng: b.getSouthWest().lng },
          northEast: { lat: b.getNorthEast().lat, lng: b.getNorthEast().lng }
        }
      };
      if (busStore.socket?.readyState === WebSocket.OPEN) {
        busStore.socket.send(JSON.stringify(msg));
      }
    };

    map.on('moveend', sendBounds);
    setTimeout(sendBounds, 1000);
  });
</script>

<div class="glass-hud">
  <div class="status-row">
    <div class="indicator" class:online={busStore.isConnected}></div>
    <div class="label">{busStore.isConnected ? 'NEXUS ONLINE' : 'LINK OFFLINE'}</div>
  </div>
  <div class="stats-row">
    <div class="big-number">{busStore.count.toLocaleString()}</div>
    <div class="sub-label">ACTIVE TERMINALS</div>
  </div>
</div>

<div bind:this={mapElement} class="map-container"></div>

<style>
  :global(body) { margin: 0; background: #050505; overflow: hidden; }
  .map-container { width: 100vw; height: 100vh; background: #050505; }

  .glass-hud {
    position: absolute;
    top: 25px;
    right: 25px;
    z-index: 2000;
    background: rgba(10, 10, 15, 0.85);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
    padding: 15px 20px;
    font-family: 'Inter', system-ui, sans-serif;
    color: #fff;
    min-width: 180px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    pointer-events: none;
  }

  .status-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .indicator { width: 8px; height: 8px; background: #ff3e00; border-radius: 50%; box-shadow: 0 0 10px #ff3e00; }
  .indicator.online { background: #00ff88; box-shadow: 0 0 15px #00ff88; animation: breathe 2s infinite; }
  .label { font-size: 10px; font-weight: 800; letter-spacing: 2px; color: rgba(255,255,255,0.5); }
  .big-number { font-size: 38px; font-weight: 900; line-height: 1; color: #fff; }
  .sub-label { font-size: 9px; font-weight: 600; color: #00ff88; letter-spacing: 1px; margin-top: 4px; }

  @keyframes breathe { 
    0%, 100% { opacity: 1; transform: scale(1); } 
    50% { opacity: 0.6; transform: scale(0.9); } 
  }
</style>
