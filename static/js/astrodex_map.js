// Astrodex Photo Map - world map view of geotagged Astrodex pictures with marker
// clustering (Apple/Google Photos style bubbles). Clicking a cluster bubble opens
// the slideshow directly for all photos in that cluster; clicking a single pin
// opens the slideshow for that one photo. Gated server-side by its own dedicated
// config['astrodex']['map_private'] flag (see /api/astrodex/map) - independent
// from the general Astrodex sharing flag.

let _astrodexPhotoMap = null;
let _astrodexMapClusterGroup = null;
const _astrodexMarkerClusterLoadState = { promise: null };

function _ensureAstrodexMarkerClusterLoaded() {
    return ensureVendorScriptLoaded(
        () => typeof L !== 'undefined' && typeof L.markerClusterGroup === 'function',
        '/static/vendor/leaflet.markercluster/dist/leaflet.markercluster.js?v=1.5.3',
        [
            '/static/vendor/leaflet.markercluster/dist/MarkerCluster.css?v=1.5.3',
            '/static/vendor/leaflet.markercluster/dist/MarkerCluster.Default.css?v=1.5.3',
        ],
        _astrodexMarkerClusterLoadState,
        'Leaflet.markercluster'
    );
}

async function loadAstrodexPhotoMap() {
    const container = document.getElementById('astrodex-photo-map');
    if (!container) return;

    DOMUtils.setLoading(container, i18n.t('common.loading'));

    try {
        const data = await fetchJSON('/api/astrodex/map');
        await _renderAstrodexPhotoMap(data);
    } catch (error) {
        console.error('Error loading Astrodex photo map:', error);
        showMessage('error', i18n.t('astrodex.failed_to_load_astrodex'));
    }
}

function destroyAstrodexPhotoMap() {
    if (_astrodexPhotoMap) {
        try { _astrodexPhotoMap.remove(); } catch (_) { /* already gone */ }
    }
    _astrodexPhotoMap = null;
    _astrodexMapClusterGroup = null;
}

function _renderAstrodexMapWithoutLocationLine(count) {
    const lineContainer = document.getElementById('astrodex-map-without-location-line');
    if (!lineContainer) return;
    DOMUtils.clear(lineContainer);
    if (!count) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'alert alert-secondary d-flex align-items-center gap-2 mb-3';
    wrapper.appendChild(DOMUtils.createIcon('bi bi-info-circle'));
    const text = document.createElement('span');
    text.textContent = i18n.t('astrodex.map_photos_without_location', { count });
    wrapper.appendChild(text);
    lineContainer.appendChild(wrapper);
}

function _openAstrodexMapPoints(points) {
    if (!Array.isArray(points) || points.length === 0) return;

    const title = points.length === 1
        ? (points[0].item_name || i18n.t('astrodex.map_title'))
        : i18n.t('astrodex.map_cluster_title', {
            count: points.length,
            location: points[0].location_name || points[0].item_name || '',
        });

    if (typeof showPictureSlideshowFromPictures === 'function') {
        showPictureSlideshowFromPictures(points, { title });
    }
}

async function _renderAstrodexPhotoMap(data) {
    const container = document.getElementById('astrodex-photo-map');
    if (!container) return;

    destroyAstrodexPhotoMap();
    DOMUtils.clear(container);

    const points = Array.isArray(data.points) ? data.points : [];
    _renderAstrodexMapWithoutLocationLine(data.total_without_location || 0);

    if (points.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'text-center text-muted p-5';
        empty.textContent = i18n.t('astrodex.map_no_points');
        container.appendChild(empty);
        return;
    }

    try {
        await _ensureLocationsLeafletLoaded();
        await _ensureAstrodexMarkerClusterLoaded();
    } catch (error) {
        console.warn('Leaflet/Leaflet.markercluster failed to load; Photo Map unavailable', error);
        const failed = document.createElement('div');
        failed.className = 'text-center text-muted p-5';
        failed.textContent = i18n.t('astrodex.failed_to_load_astrodex');
        container.appendChild(failed);
        return;
    }

    if (!document.body.contains(container)) return; // sub-tab switched away while loading

    const map = L.map(container, {
        zoomControl: true,
        scrollWheelZoom: true,
    });

    // CartoDB Voyager (light), not the dark_all basemap used by the orbital
    // stations map - Photo Map browses real-world geographic diversity, and
    // dark tiles render remote/rural astrophotography sites near-blank.
    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        maxZoom: 18,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);

    // Clicking a cluster bubble opens the slideshow for its photos directly
    // rather than zooming/spiderfying toward them - the user can still zoom
    // the map itself (scroll/pinch/+/-) to let clusters separate naturally.
    const clusterGroup = L.markerClusterGroup({
        spiderfyOnMaxZoom: false,
        zoomToBoundsOnClick: false,
        showCoverageOnHover: false,
    });

    points.forEach(point => {
        if (!Number.isFinite(Number(point.latitude)) || !Number.isFinite(Number(point.longitude))) return;
        const marker = L.marker([Number(point.latitude), Number(point.longitude)]);
        marker.astrodexPoint = point;
        marker.on('click', () => _openAstrodexMapPoints([point]));
        clusterGroup.addLayer(marker);
    });

    clusterGroup.on('clusterclick', (event) => {
        const clusterPoints = event.layer.getAllChildMarkers()
            .map(childMarker => childMarker.astrodexPoint)
            .filter(Boolean);
        _openAstrodexMapPoints(clusterPoints);
    });

    map.addLayer(clusterGroup);

    const bounds = clusterGroup.getBounds();
    if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
    } else {
        map.setView([20, 0], 2);
    }

    _astrodexPhotoMap = map;
    _astrodexMapClusterGroup = clusterGroup;

    // Leaflet must measure a visible, sized container - the sub-tab has just
    // become active, so defer the size check by a frame to be safe (same
    // gotcha documented in locations.js / _updatePictureLocationMap()).
    requestAnimationFrame(() => {
        try { map.invalidateSize(); } catch (_) { /* map already torn down */ }
    });
}
