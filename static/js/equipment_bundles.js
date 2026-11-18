/**
 * Smart-telescope preset bundles (static/data/equipment_presets.json).
 *
 * A telescope preset can carry a `bundle`: the camera, mount and filters built into the same
 * unit (Seestar, Dwarf, Vespera, Atlas...). This module turns a bundle into real equipment and
 * one combination linking it all, so the result can be framed and scored like any other setup.
 * Shared by the guided setup wizard (first_run.js) and the Equipment tab (equipment.js).
 * See docs/EQUIPMENT.md#bundles-smart-telescopes.
 */

/* global fetchJSON, appUrl */

const EQUIPMENT_PRESET_SENSOR_TYPE_MAP = {
    cmos_color: 'CMOS Color',
    dslr_color: 'CMOS Color',
    mirrorless_color: 'CMOS Color',
    cmos_mono: 'CMOS Mono',
    ccd_color: 'CCD Color',
    ccd_mono: 'CCD Mono',
};

const _BUNDLE_ENDPOINT_BY_KIND = {
    camera: appUrl('/api/equipment/cameras'),
    mount: appUrl('/api/equipment/mounts'),
    filter: appUrl('/api/equipment/filters'),
    accessory: appUrl('/api/equipment/accessories'),
};

/** True when a telescope preset brings its own built-in equipment. */
function isBundlingPreset(preset) {
    return !!preset && preset.auto_combination !== false && Array.isArray(preset.bundle) && preset.bundle.length > 0;
}

/** Map a camera preset (standalone or bundle entry) to its create payload. */
function mapCameraPresetToPayload(preset) {
    return {
        name: preset.label,
        manufacturer: preset.manufacturer || '',
        sensor_width_mm: preset.sensor_width_mm,
        sensor_height_mm: preset.sensor_height_mm,
        resolution_width_px: preset.resolution_w,
        resolution_height_px: preset.resolution_h,
        pixel_size_um: preset.pixel_size_um,
        sensor_type: EQUIPMENT_PRESET_SENSOR_TYPE_MAP[preset.type] || 'CMOS Color',
        weight_kg: preset.weight_kg || 0,
        cooling_supported: preset.cooling_supported || false,
        min_temperature_c: preset.min_temperature_c ?? null,
    };
}

/** Map a bundle entry (same field shape as a standalone preset of its kind) to its create payload. */
function mapBundleItemToPayload(kind, item) {
    if (kind === 'camera') return mapCameraPresetToPayload(item);
    if (kind === 'mount') {
        return {
            name: item.label,
            manufacturer: item.manufacturer || '',
            mount_type: item.mount_type || 'Alt-Azimuth',
            payload_capacity_kg: item.payload_capacity_kg || 0,
            guiding_supported: item.guiding_supported || false,
        };
    }
    if (kind === 'filter') {
        return {
            name: item.label,
            manufacturer: item.manufacturer || '',
            filter_type: item.filter_type || 'Other',
            central_wavelength_nm: item.central_wavelength_nm ?? null,
            bandwidth_nm: item.bandwidth_nm ?? null,
            intended_use: item.intended_use || '',
        };
    }
    if (kind === 'accessory') {
        return {
            name: item.label,
            manufacturer: item.manufacturer || '',
            accessory_type: item.accessory_type || '',
            weight_kg: item.weight_kg || 0,
        };
    }
    return null;
}

/**
 * Create every item of a bundle. Returns the created ids grouped by combination field.
 * Best-effort: one failed item is logged and skipped rather than aborting the rest.
 * @param {Object[]} bundle
 * @returns {Promise<{camera_id: ?string, mount_id: ?string, filter_ids: string[], accessory_ids: string[]}>}
 */
async function createBundleItems(bundle) {
    const created = { camera_id: null, mount_id: null, filter_ids: [], accessory_ids: [] };
    for (const item of bundle || []) {
        const endpoint = _BUNDLE_ENDPOINT_BY_KIND[item.kind];
        const payload = mapBundleItemToPayload(item.kind, item);
        if (!endpoint || !payload) continue;
        try {
            const result = await fetchJSON(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const id = result?.data?.id;
            if (!id) continue;
            if (item.kind === 'camera') created.camera_id = id;
            else if (item.kind === 'mount') created.mount_id = id;
            else if (item.kind === 'filter') created.filter_ids.push(id);
            else if (item.kind === 'accessory') created.accessory_ids.push(id);
        } catch (err) {
            console.error(`Bundle item (${item.kind}) create error:`, err);
        }
    }
    return created;
}

/**
 * Create a bundling telescope preset's built-in items and the combination linking them to an
 * already created telescope.
 * @param {Object} preset - telescope preset with a bundle
 * @param {string} telescopeId - id of the telescope created from that preset
 * @param {string} [name] - combination name, defaults to the preset label
 * @returns {Promise<?Object>} the created combination, or null when it could not be created
 */
async function createBundleCombination(preset, telescopeId, name) {
    const created = await createBundleItems(preset.bundle);
    const result = await fetchJSON(appUrl('/api/equipment/combinations'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: name || preset.label,
            telescope_id: telescopeId || null,
            camera_id: created.camera_id,
            mount_id: created.mount_id,
            filter_ids: created.filter_ids,
            accessory_ids: created.accessory_ids,
        }),
    });
    return result?.data || null;
}

/**
 * The built-in cameras of the bundling telescope presets, as camera presets. Offered in the
 * Equipment tab's camera form so a smart telescope saved without its camera can be completed.
 * @param {Object[]} telescopePresets
 * @returns {Object[]}
 */
function bundleCameraPresets(telescopePresets) {
    const cameras = [];
    (telescopePresets || []).forEach((preset) => {
        (preset.bundle || []).forEach((item) => {
            if (item.kind === 'camera') cameras.push(item);
        });
    });
    return cameras;
}
