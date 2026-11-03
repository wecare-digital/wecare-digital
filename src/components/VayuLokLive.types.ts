/**
 * Shared type/interface declarations for VayuLokLive.
 *
 * These were extracted VERBATIM from src/components/VayuLokLive.tsx as part of a pure
 * structural refactor (no behaviour change). The component file re-exports
 * VayuLokExternalLocation so its public type surface is unchanged for importers.
 */

export type CurrencySide = 'base' | 'quote';

export interface PlaceState {
  name: string;
  addr: string;
  lat: number;
  lng: number;
  placeId?: string;
  viewport?: { north: number; south: number; east: number; west: number };
  regionCode?: string;
}

export interface SearchResult {
  name: string;
  addr: string;
  place?: PlaceState;
  prediction?: {
    placeId?: string;
    toPlace?: () => { id?: string };
  };
}

/* ---- AQI category + severity-form mapping ------------------------------------------
   India AQI (CPCB) bands. Severity is encoded by FORM (dot/bar class) AND the category
   WORD in text, never colour alone (WCAG 1.4.1). NO red anywhere - the ramp walks dark
   green -> lime -> amber, matching the mock's severity ramp. */
export type Sev = 'good' | 'sat' | 'mod' | 'poor' | 'worst';

/* ---- Health recommendation personas -------------------------------------------------
   Google Air Quality currentConditions returns tailored guidance for seven supported
   populations. These definitions contain LABEL + API KEY + Google Material Symbol only:
   recommendation copy always comes from Google's response, never from static fallback text. */
export type HealthRecommendationKey =
  | 'generalPopulation'
  | 'elderly'
  | 'lungDiseasePopulation'
  | 'heartDiseasePopulation'
  | 'athletes'
  | 'pregnantWomen'
  | 'children';

export type HealthPersonaIcon =
  | 'general'
  | 'elderly'
  | 'respiratory'
  | 'heart'
  | 'athletes'
  | 'pregnant'
  | 'children';

export interface HealthPersonaDefinition {
  id: string;
  label: string;
  apiKey: HealthRecommendationKey;
  icon: HealthPersonaIcon;
}

/* ---- live data shapes ---------------------------------------------------------------
   Every field is optional: a value only enters state once it actually arrived, so the
   markup renders only the fields that are present and never a placeholder. */
export interface AirIndexInfo {
  code: string;
  displayName?: string;
  aqi: number;
  aqiDisplay?: string;
  category?: string;
  dominantPollutant?: string;
  regionCode?: string;
  color?: { red?: number; green?: number; blue?: number };
}

export interface AirState {
  aqi: number;
  word: string;
  sev: Sev;
  indexName?: string;
  indexCode?: string;
  aqiDisplay?: string;
  regionCode?: string;
  indexes?: AirIndexInfo[];
  universalIndex?: AirIndexInfo;
  localIndex?: AirIndexInfo;
  dominant?: string;
  pollutants: {
    code: string;
    label: string;
    fullName?: string;
    value: number;
    unit: string;
    sources?: string;
    effects?: string;
  }[];
  healthRecommendations?: Partial<Record<HealthRecommendationKey, string>>;
  advisory?: string;
  updatedAt?: string;
}

export interface LocationTimeState {
  timeZoneId: string;
  timeZoneName: string;
  shortLabel: string;
  source: 'default' | 'google' | 'fixed' | 'pending' | 'unavailable';
}

export type UtilityPlaceSlot = 'world-from' | 'world-to' | 'route-from' | 'route-to';

export interface RouteResultState {
  durationSeconds: number;
  distanceMeters: number;
  encodedPolyline?: string;
}

export interface WorldTimeDestination {
  name: string;
  addr: string;
  lat: number;
  lng: number;
  regionCode?: string;
  time: LocationTimeState;
}

export interface FxRateState {
  base: string;
  quote: string;
  rate: number;
  date: string;
  ts: number;
}

export interface WeatherState {
  temp?: number;
  feelsLike?: number;
  humidity?: number;
  windSpeed?: number;
  windUnit?: string;
  windDir?: string;
  windDeg?: number;
  windGust?: number;
  rainMm?: number;
  rainProb?: number;
  stormProb?: number;
  uv?: number;
  visibilityKm?: number;
  pressureHpa?: number;
  dewPoint?: number;
  heatIndex?: number;
  wetBulb?: number;
  cloudCover?: number;
  condition?: string;
  currentTime?: string;
  // Added for the Weather tab: Google returns these on currentConditions and in its
  // currentConditionsHistory block (no extra API call needed).
  icon?: string;
  isDaytime?: boolean;
  windChill?: number;
  precipitationType?: string;
  temperatureChange?: number;
  dayMin?: number;
  dayMax?: number;
  recentQpf?: number;
}
export interface WeatherHour {
  time: number;
  temp?: number;
  feelsLike?: number;
  rainProb?: number;
  rainMm?: number;
  stormProb?: number;
  uv?: number;
  windSpeed?: number;
  windUnit?: string;
  windDir?: string;
  windDeg?: number;
  condition?: string;
  icon?: string;
  // Added for the hourly detail panel: the richer dimensions Google already returns per hour.
  humidity?: number;
  dewPoint?: number;
  heatIndex?: number;
  windChill?: number;
  wetBulb?: number;
  windGust?: number;
  visibilityKm?: number;
  pressureHpa?: number;
  cloudCover?: number;
  precipitationType?: string;
  iceThicknessMm?: number;
}
export interface WeatherDay {
  time: number;
  label: string;
  dateLabel: string;
  min?: number;
  max?: number;
  rainProb?: number;
  condition?: string;
  icon?: string;
  sunrise?: string;
  sunset?: string;
  // Added for the daily detail panel.
  nightCondition?: string;
  nightIcon?: string;
  dayDetails?: WeatherPeriodDetail;
  nightDetails?: WeatherPeriodDetail;
  feelsLikeMin?: number;
  feelsLikeMax?: number;
  humidity?: number;
  uv?: number;
  rainMm?: number;
  stormProb?: number;
  windSpeed?: number;
  windUnit?: string;
  windDir?: string;
  windGust?: number;
  precipitationType?: string;
  pressureHpa?: number;
  cloudCover?: number;
  visibilityKm?: number;
  heatIndex?: number;
  windChill?: number;
  iceThicknessMm?: number;
  moonrise?: string;
  moonset?: string;
  moonPhase?: string;
}
export interface WeatherPeriodDetail {
  condition?: string;
  icon?: string;
  humidity?: number;
  uv?: number;
  rainProb?: number;
  rainMm?: number;
  stormProb?: number;
  windSpeed?: number;
  windUnit?: string;
  windDir?: string;
  windGust?: number;
  precipitationType?: string;
  pressureHpa?: number;
  cloudCover?: number;
  visibilityKm?: number;
  heatIndex?: number;
  windChill?: number;
}
export interface AirPoint {
  time: number;
  aqi: number;
  word: string;
  pm25?: number;
  dominant?: string;
  indexCode?: string;
  localAqi?: number;
  universalAqi?: number;
  healthRecommendations?: Partial<Record<HealthRecommendationKey, string>>;
  pollutants?: {
    code: string;
    label?: string;
    fullName?: string;
    value: number;
    unit: string;
    sources?: string;
    effects?: string;
  }[];
}
export interface WeatherAlertRow {
  id: string;
  title: string;
  eventType?: string;
  description?: string;
  area?: string;
  polygon?: string;
  severity?: string;
  certainty?: string;
  urgency?: string;
  instruction?: string[];
  safetyRecommendations?: { directive: string; subtext?: string }[];
  startTime?: string;
  expires?: string;
  timezoneOffset?: string;
  // Google requires the originating authority to be attributed when an alert is shown.
  source?: string;
  sourcePublisher?: string;
  sourceUrl?: string;
}

export interface VayuLokExternalLocation {
  name: string;
  addr?: string;
  lat: number;
  lng: number;
  regionCode?: string;
}

export interface VayuLokLiveProps {
  mode?: 'air' | 'weather';
  onModeChange?: ( mode: 'air' | 'weather' ) => void;
  externalLocation?: VayuLokExternalLocation | null;
}
