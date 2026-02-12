<script>
  import { onMount } from 'svelte';
  import L from 'leaflet';
  import { busStore } from './busStore.svelte.js';

  let mapElement;
  let map;
  
  const easeOut = (t) => t * (2 - t);

  onMount(() => {
    map = L.map(mapElement, { 
      attributionControl: false,
      zoomControl: false,
      center: [55.751244, 37.618423],
      zoom: 13,
      preferCanvas: true
    });

    // CartoDB Dark Matter - стандарт красивой темной карты
    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png', {
        className: 'soft-dark-map',
        keepBuffer: 4
    }).addTo(map);

    L.BusLayer = L.Layer.extend({
      onAdd: function(map) {
        this._map = map;
        this._canvas = L.DomUtil.create('canvas', 'leaflet-bus-layer');
        this._canvas.style.position = 'absolute';
        this._canvas.style.pointerEvents = 'none';
        this._canvas.style.zIndex = '999';
        
        map.getPanes().overlayPane.appendChild(this._canvas);
        this._ctx = this._canvas.getContext('2d', { alpha: true });
        
        map.on('move zoom viewreset', this._reset, this);
        this._reset();
        this._animate();
      },

      onRemove: function(map) {
        map.getPanes().overlayPane.removeChild(this._canvas);
        cancelAnimationFrame(this._requestId);
      },

      _reset: function() {
        const size = this._map.getSize();
        const topLeft = this._map.containerPointToLayerPoint([0, 0]);
        L.DomUtil.setPosition(this._canvas, topLeft);
        
        if (this._canvas.width !== size.x || this._canvas.height !== size.y) {
          this._canvas.width = size.x;
          this._canvas.height = size.y;
        }
        this._layerOffset = topLeft;
      },

      _animate: function() {
        this._draw();
        this._requestId = requestAnimationFrame(this._animate.bind(this));
      },

      _draw: function() {
        if (!this._map) return;
        const ctx = this._ctx;
        const width = this._canvas.width;
        const height = this._canvas.height;
        const now = performance.now();
        const duration = 250; 

        ctx.clearRect(0, 0, width, height);
        
        const buses = busStore.buses;
        const offset = this._layerOffset;

        const groups = Array.from({length: 10}, () => []);

        for (const bus of buses.values()) {
          let t = (now - bus.startTime) / duration;
          if (t > 1) t = 1;
          const easedT = easeOut(t);
          
          const lat = bus.startLat + (bus.targetLat - bus.startLat) * easedT;
          const lng = bus.startLng + (bus.targetLng - bus.startLng) * easedT;
          bus.curLat = lat; bus.curLng = lng;

          const lp = this._map.latLngToLayerPoint([lat, lng]);
          const x = lp.x - offset.x;
          const y = lp.y - offset.y;

          if (x < -20 || y < -20 || x > width + 20 || y > height + 20) continue;
          groups[Math.floor(bus.route % 10)].push(x, y);
        }

        ctx.lineWidth = 0.5;
        ctx.strokeStyle = "rgba(255,255,255,0.8)";
        groups.forEach((coords, i) => {
          if (coords.length === 0) return;
          ctx.beginPath();
          ctx.fillStyle = `hsl(${(i * 36) % 360}, 100%, 65%)`;
          for (let j = 0; j < coords.length; j += 2) {
            const x = coords[j], y = coords[j+1];
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
    if (map.getBounds()) sendBounds();

    return () => {
      map.off('moveend', sendBounds);
      map.remove();
    };
  });
</script>

<div class="glass-hud">
  <div class="header">
    <div class="status" class:online={busStore.isConnected}>
      <div class="dot"></div>
      <span>{busStore.isConnected ? 'NEXUS ACTIVE' : 'LINK LOST'}</span>
    </div>
    <div class="ups">
      <span class="value">{busStore.ups}</span>
      <span class="label">UPS</span>
    </div>
  </div>
  <div class="main-stats">
    <div class="big-number">{busStore.count.toLocaleString()}</div>
    <div class="sub-label">TRACKED UNITS</div>
  </div>
</div>

<div bind:this={mapElement} class="map-container"></div>

<style>
  :global(body) { margin: 0; background: #1a1a1a; overflow: hidden; }
  .map-container { width: 100vw; height: 100vh; background: #1a1a1a; }

  /* Делаем карту чуть светлее (темно-серый графит) */
  :global(.soft-dark-map) { 
    filter: brightness(1.5) contrast(1.1) saturate(1.5); 
  } 

  .glass-hud {
    position: absolute; top: 25px; right: 25px; z-index: 2000;
    background: rgba(30, 30, 35, 0.8);
    backdrop-filter: blur(15px); -webkit-backdrop-filter: blur(15px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px; padding: 15px 20px;
    font-family: 'Inter', system-ui, sans-serif; color: #fff;
    min-width: 200px; box-shadow: 0 15px 35px rgba(0,0,0,0.4);
    pointer-events: none;
  }

  .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 8px; }
  .status { display: flex; align-items: center; gap: 8px; color: #ff3e00; font-size: 9px; font-weight: 800; letter-spacing: 1px; }
  .status.online { color: #00ff88; }
  .dot { width: 6px; height: 6px; background: currentColor; border-radius: 50%; box-shadow: 0 0 8px currentColor; }
  .ups .value { font-size: 11px; font-weight: 900; color: #00ffcc; font-variant-numeric: tabular-nums; }
  .ups .label { font-size: 8px; color: rgba(255,255,255,0.3); margin-left: 4px; }
  .big-number { font-size: 48px; font-weight: 900; line-height: 1; color: #fff; letter-spacing: -1px; }
  .sub-label { font-size: 10px; font-weight: 700; color: rgba(255,255,255,0.4); letter-spacing: 2px; margin-top: 5px; }
</style>
