// Pure BigQuery decoding and historical-weather normalization. No I/O.

function finiteNumber(value) {
  if (typeof value !== 'number' && typeof value !== 'string') return null;
  if (typeof value === 'string' && value.trim() === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function parseNumber(value, min, max) {
  const n = finiteNumber(value);
  return n !== null && n >= min && n <= max ? n : null;
}

function decodeValue(field, cell) {
  if (!cell || cell.v === null || cell.v === undefined) return null;
  // BigQuery repeated RECORD cells are arrays, not single record objects.
  if (field.mode === 'REPEATED') {
    return Array.isArray(cell.v)
      ? cell.v.map((item) => decodeValue({ ...field, mode: 'NULLABLE' }, item))
      : null;
  }
  if (field.type === 'RECORD' || field.type === 'STRUCT') {
    if (!Array.isArray(cell.v?.f)) return null;
    const nested = {};
    (field.fields || []).forEach((child, index) => {
      nested[child.name] = decodeValue(child, cell.v.f[index]);
    });
    return nested;
  }
  const value = cell.v;
  if (['INTEGER', 'INT64', 'FLOAT', 'FLOAT64', 'NUMERIC', 'BIGNUMERIC'].includes(field.type)) {
    return finiteNumber(value);
  }
  if (field.type === 'BOOLEAN' || field.type === 'BOOL') return value === true || value === 'true';
  if (field.type === 'TIMESTAMP') {
    const seconds = finiteNumber(value);
    if (seconds !== null) {
      const timestamp = new Date(seconds * 1000);
      return Number.isFinite(timestamp.getTime()) ? timestamp.toISOString() : null;
    }
    return null;
  }
  return value;
}

export function decodeRows(result) {
  const fields = result.schema?.fields || [];
  return (result.rows || []).map((row) => {
    const out = {};
    fields.forEach((field, index) => {
      out[field.name] = decodeValue(field, row.f?.[index]);
    });
    return out;
  });
}

export function cleanSummary(row, range) {
  const sampleHours = finiteNumber(row?.sample_hours);
  if (!Number.isSafeInteger(sampleHours) || sampleHours <= 0) return null;
  const round = (value, digits = 1) => {
    const n = finiteNumber(value);
    if (n === null) return null;
    const scale = 10 ** digits;
    const rounded = Math.round(n * scale) / scale;
    return Number.isFinite(rounded) ? rounded : null;
  };
  const monthly = Array.isArray(row.monthly) ? row.monthly.flatMap((item) => {
    const month = finiteNumber(item?.month);
    if (!Number.isInteger(month) || month < 1 || month > 12) return [];
    return [{
      month,
      meanTemperatureC: round(item.mean_temperature_c),
      precipitationMm: round(item.precipitation_mm),
      meanHumidityPct: round(item.mean_humidity_pct),
    }];
  }) : [];
  return {
    range,
    coverageStart: row.coverage_start || null,
    coverageEnd: row.coverage_end || null,
    gridDistanceKm: round(row.grid_distance_km, 2),
    sampleHours,
    meanTemperatureC: round(row.mean_temperature_c),
    minTemperatureC: round(row.min_temperature_c),
    maxTemperatureC: round(row.max_temperature_c),
    precipitationMm: round(row.precipitation_mm),
    meanHumidityPct: round(row.mean_humidity_pct),
    monthly,
  };
}
