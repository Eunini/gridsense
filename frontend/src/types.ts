export type Reading = {
  event_id: string;
  device_id: string;
  recorded_at: string;
  grid_voltage_v: number;
  load_w: number;
  solar_w: number;
  battery_soc_pct: number;
  battery_power_w: number;
};
export type Site = { id: number; name: string; location: string };
export type Outage = {
  started_at: string;
  ended_at: string;
  ongoing: boolean;
  interrupted_by_gap: boolean;
  duration_minutes: number;
};
export type Alert = {
  event_id: string;
  recorded_at: string;
  kind: string;
  severity: string;
  message: string;
};
export type Overview = {
  site: Site;
  device_id: string | null;
  hours: number;
  demo_mode: boolean;
  generated_at: string;
  last_seen: string | null;
  stale: boolean;
  current: Reading | null;
  summary: {
    load_kwh: number;
    solar_kwh: number;
    grid_availability_pct: number | null;
    coverage_pct: number;
    observed_hours: number;
    battery_reserve_hours: number | null;
  };
  series: Reading[];
  outages: Outage[];
  alerts: Alert[];
};
export type Forecast = {
  method: string;
  note: string;
  points: {
    recorded_at: string;
    load_w: number;
    solar_w: number;
    lower_w: number;
    upper_w: number;
  }[];
  backtest: {
    mae_w: number;
    persistence_mae_w: number;
    holdout_samples: number;
  } | null;
};
