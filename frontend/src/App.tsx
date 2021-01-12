import { useCallback, useEffect, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  ArrowsClockwise,
  ArrowUpRight,
  BatteryCharging,
  ChartLine,
  CheckCircle,
  CloudSlash,
  Database,
  DownloadSimple,
  Flask,
  GithubLogo,
  HouseLine,
  Lightning,
  MapPin,
  Pause,
  Play,
  Plug,
  Stack,
  Sun,
  WarningCircle,
  WifiHigh,
  WifiSlash,
} from "@phosphor-icons/react";
import {
  flushReadings,
  loadSnapshot,
  pendingReadings,
  queueReading,
  saveSnapshot,
} from "./outbox";
import type { Forecast, Overview, Reading, Site } from "./types";

const time = (value: string | number) =>
  new Date(value).toLocaleTimeString("en-GB", {
    timeZone: "Africa/Lagos",
    hour: "2-digit",
    minute: "2-digit",
  });
const date = (value: string) =>
  new Date(value).toLocaleDateString("en-GB", {
    timeZone: "Africa/Lagos",
    day: "numeric",
    month: "short",
  });
const kw = (value: number | undefined) =>
  value === undefined ? "—" : (value / 1000).toFixed(2);
const duration = (minutes: number) =>
  minutes < 1
    ? "< 1 min"
    : minutes >= 60
      ? `${Math.floor(minutes / 60)}h ${Math.round(minutes % 60)}m`
      : `${Math.round(minutes)} min`;

export default function App() {
  const [tab, setTab] = useState("Overview");
  const [hours, setHours] = useState(24);
  const [sites, setSites] = useState<Site[]>([]);
  const [siteId, setSiteId] = useState(1);
  const [data, setData] = useState<Overview>();
  const [prediction, setPrediction] = useState<Forecast>();
  const [paused, setPaused] = useState(false);
  const [cached, setCached] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [scenario, setScenario] = useState("outage");
  const [queued, setQueued] = useState(0);
  const [uplinkOffline, setUplinkOffline] = useState(false);
  const [demo, setDemo] = useState<{
    device_id: string;
    device_token: string;
  }>();
  const [authRequired, setAuthRequired] = useState(false);
  const [token, setToken] = useState(
    () => sessionStorage.getItem("gridsense-operator") || "",
  );
  const [tokenInput, setTokenInput] = useState("");
  const controller = useRef<AbortController | null>(null);
  const headers = useCallback(
    (): HeadersInit => (token ? { Authorization: `Bearer ${token}` } : {}),
    [token],
  );

  const refresh = useCallback(async () => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    try {
      const responses = await Promise.all([
        fetch(`/api/sites/${siteId}/overview?hours=${hours}`, {
          signal: abort.signal,
          headers: headers(),
        }),
        fetch(`/api/sites/${siteId}/forecast`, {
          signal: abort.signal,
          headers: headers(),
        }),
      ]);
      if (responses.some((response) => response.status === 401)) {
        setAuthRequired(true);
        return;
      }
      if (responses.some((response) => !response.ok))
        throw new Error("The monitoring API is unavailable.");
      const [overview, forecast] = (await Promise.all(
        responses.map((response) => response.json()),
      )) as [Overview, Forecast];
      if (abort.signal.aborted) return;
      setData(overview);
      setPrediction(forecast);
      setCached(false);
      setError("");
      setAuthRequired(false);
      if (overview.demo_mode) {
        await saveSnapshot(`overview-${siteId}-${hours}`, overview);
        await saveSnapshot(`forecast-${siteId}`, forecast);
      }
    } catch (cause) {
      if (abort.signal.aborted) return;
      const snapshot = await loadSnapshot<Overview>(
        `overview-${siteId}-${hours}`,
      ).catch(() => undefined);
      if (snapshot && !token) {
        setData(snapshot);
        setPrediction(await loadSnapshot<Forecast>(`forecast-${siteId}`));
        setCached(true);
        setError("Connection lost. Showing the last saved demo snapshot.");
      } else
        setError(
          cause instanceof Error ? cause.message : "Unable to load telemetry.",
        );
    }
  }, [siteId, hours, headers, token]);

  useEffect(() => {
    fetch("/api/sites", { headers: headers() })
      .then(async (response) => {
        if (response.status === 401) {
          setAuthRequired(true);
          return;
        }
        if (!response.ok) return;
        const available = (await response.json()) as Site[];
        setSites(available);
        if (available.length && !available.some((site) => site.id === siteId))
          setSiteId(available[0].id);
      })
      .catch(() => {});
    const loadDemoConfig = async () => {
      try {
        const response = await fetch("/api/demo/config");
        const config = response.ok ? await response.json() : undefined;
        setDemo(config);
        if (config) await saveSnapshot("demo-config", config);
      } catch {
        setDemo(
          await loadSnapshot<{ device_id: string; device_token: string }>(
            "demo-config",
          ).catch(() => undefined),
        );
      }
    };
    void loadDemoConfig();
    const online = () => {
      void loadDemoConfig();
      void refresh();
    };
    window.addEventListener("online", online);
    pendingReadings()
      .then((rows) => setQueued(rows.length))
      .catch(() => setError("Browser storage is unavailable."));
    return () => window.removeEventListener("online", online);
  }, [headers, siteId, refresh]);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => {
      if (!paused) void refresh();
    }, 20_000);
    return () => {
      window.clearInterval(interval);
      controller.current?.abort();
    };
  }, [refresh, paused]);

  async function action(work: () => Promise<void>) {
    setBusy(true);
    setNotice("");
    try {
      await work();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Action failed.");
    } finally {
      setBusy(false);
      setQueued((await pendingReadings().catch(() => [])).length);
    }
  }

  async function sync() {
    if (!demo) return;
    const count = await flushReadings(demo.device_token);
    setNotice(
      `${count} queued reading${count === 1 ? "" : "s"} acknowledged by the server.`,
    );
    await refresh();
  }

  async function collect() {
    if (!data?.current || !demo) return;
    const reading: Reading = {
      ...data.current,
      event_id: crypto.randomUUID(),
      device_id: demo.device_id,
      recorded_at: new Date().toISOString(),
      load_w: Math.round(data.current.load_w * (0.96 + Math.random() * 0.08)),
    };
    await queueReading(reading);
    if (!uplinkOffline && navigator.onLine) await sync();
    else
      setNotice(
        "Sample saved to this browser. It will remain queued across reloads.",
      );
  }

  async function runScenario() {
    const response = await fetch("/api/demo/scenario", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: scenario }),
    });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body.detail || "Scenario failed.");
    }
    await refresh();
    setNotice("Scenario applied. Two simulated observations were added.");
  }

  async function exportCsv() {
    const response = await fetch(`/api/sites/${siteId}/export?hours=${hours}`, {
      headers: headers(),
    });
    if (!response.ok) throw new Error("Export failed. Please retry.");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "gridsense-readings.csv";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice("CSV export downloaded.");
  }

  const current = data?.current;
  const gridDown = current ? current.grid_voltage_v < 180 : false;
  const chart = (data?.series || []).map((row) => ({
    timestamp: new Date(row.recorded_at).getTime(),
    Load: row.load_w / 1000,
    Solar: row.solar_w / 1000,
  }));
  const forecastChart = (prediction?.points || []).map((point) => ({
    timestamp: new Date(point.recorded_at).getTime(),
    Load: point.load_w / 1000,
    Solar: point.solar_w / 1000,
    range: [point.lower_w / 1000, point.upper_w / 1000],
  }));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="GridSense home">
          <span className="brand-icon">
            <Lightning weight="fill" size={24} />
          </span>
          GridSense<span className="brand-period">.</span>
        </a>
        <p className="workspace-label">ENERGY WORKSPACE</p>
        <nav aria-label="Main navigation">
          {[
            ["Overview", <HouseLine size={20} />],
            ["Outages", <Plug size={20} />],
            ["Devices", <Stack size={20} />],
          ].map(([name, icon]) => (
            <button
              key={String(name)}
              className={tab === name ? "nav-item active" : "nav-item"}
              aria-pressed={tab === name}
              onClick={() => setTab(String(name))}
            >
              {icon}
              {name}
              {name === "Outages" && (
                <span className="nav-count">{data?.outages.length || 0}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <CloudSlash size={24} />
          <strong>Built for the gaps.</strong>
          <p>
            Keep collecting when the connection drops. Sync when it returns.
          </p>
        </div>
        <div className="sidebar-bottom">
          <span className="avatar">GS</span>
          <div>
            <strong>Local workspace</strong>
            <small>
              {data?.demo_mode ? "Simulation environment" : "Operator console"}
            </small>
          </div>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <span>/</span> <strong>{tab}</strong>
          </div>
          <div className="topbar-right">
            <span
              className={`connection ${cached || data?.stale ? "muted" : ""}`}
            >
              <span className="status-dot" />
              {cached
                ? "Saved snapshot"
                : data?.stale
                  ? "Telemetry stale"
                  : data
                    ? "Telemetry connected"
                    : "Connecting"}
            </span>
            <a
              href="https://github.com/Eunini/gridsense"
              target="_blank"
              rel="noreferrer"
              aria-label="View source on GitHub"
            >
              <GithubLogo size={23} />
            </a>
          </div>
        </header>
        <div className="page-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                <span className="status-dot" />
                {data?.demo_mode
                  ? "SIMULATED ENERGY DATA"
                  : "ENERGY MONITORING"}
              </div>
              <h1>
                {tab === "Overview"
                  ? "Every watt, accounted for."
                  : tab === "Outages"
                    ? "A clearer picture of downtime."
                    : "Connected through uncertainty."}
              </h1>
              <p>
                {data?.site.name || "Your energy workspace"}
                <span className="heading-dot">·</span>
                <MapPin size={15} />
                {data?.site.location || "Waiting for site data"}
                <span className="heading-dot">·</span>West Africa Time
              </p>
            </div>
            <div className="heading-actions">
              <button
                className="button"
                disabled={!data || busy}
                onClick={() => void action(exportCsv)}
              >
                <DownloadSimple size={17} />
                Export CSV
              </button>
              <button
                className="icon-button"
                aria-label={
                  paused ? "Resume live updates" : "Pause live updates"
                }
                onClick={() => setPaused(!paused)}
              >
                {paused ? <Play size={18} /> : <Pause size={18} />}
              </button>
            </div>
          </div>

          {error && (
            <div className="banner error" role="alert">
              <WarningCircle size={20} />
              <span>{error}</span>
              <button onClick={() => void refresh()}>Retry</button>
            </div>
          )}
          {notice && (
            <div className="banner success" role="status">
              <CheckCircle size={20} />
              <span>{notice}</span>
              <button aria-label="Dismiss notice" onClick={() => setNotice("")}>
                Dismiss
              </button>
            </div>
          )}
          {authRequired && (
            <form
              className="auth-panel panel"
              onSubmit={(event) => {
                event.preventDefault();
                sessionStorage.setItem("gridsense-operator", tokenInput);
                setToken(tokenInput);
                setTokenInput("");
              }}
            >
              <h2>Operator access</h2>
              <p>Enter your workspace token to view this installation.</p>
              <label htmlFor="operator-token">Operator token</label>
              <input
                id="operator-token"
                type="password"
                autoComplete="off"
                value={tokenInput}
                onChange={(event) => setTokenInput(event.target.value)}
                required
              />
              <button className="button primary" type="submit">
                Connect workspace
              </button>
            </form>
          )}

          {!data && !authRequired && (
            <div className="empty-state panel">
              <Database size={32} />
              <h2>
                {error
                  ? "Telemetry is unavailable"
                  : "Connecting to your installation…"}
              </h2>
              <p>
                {error
                  ? "Check the API connection and retry."
                  : "Loading readings, outages, and energy estimates."}
              </p>
            </div>
          )}

          {data && (
            <>
              <div className="toolbar">
                <div className="site-label">
                  <span className="installation-icon">
                    <Sun size={18} />
                  </span>
                  {sites.length > 1 ? (
                    <select
                      aria-label="Installation"
                      value={siteId}
                      onChange={(event) =>
                        setSiteId(Number(event.target.value))
                      }
                    >
                      {sites.map((site) => (
                        <option key={site.id} value={site.id}>
                          {site.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <strong>{data.site.name}</strong>
                  )}
                  <span className="subtle">
                    / {data.device_id || "No inverter"}
                  </span>
                </div>
                <div className="range-control" aria-label="Time range">
                  {[24, 72].map((value) => (
                    <button
                      key={value}
                      aria-pressed={hours === value}
                      className={hours === value ? "selected" : ""}
                      onClick={() => setHours(value)}
                    >
                      {value} hours
                    </button>
                  ))}
                </div>
              </div>

              {tab === "Overview" && (
                <>
                  <section className="metrics" aria-label="Energy metrics">
                    <Metric
                      icon={<Lightning size={19} />}
                      title="Current consumption"
                      value={kw(current?.load_w)}
                      unit="kW"
                      detail={`${data.summary.load_kwh.toFixed(1)} kWh in observed periods`}
                    />
                    <Metric
                      icon={<Sun size={19} />}
                      title="Solar generation"
                      value={kw(current?.solar_w)}
                      unit="kW"
                      detail={`${data.summary.solar_kwh.toFixed(1)} kWh in observed periods`}
                      accent
                    />
                    <Metric
                      icon={<BatteryCharging size={19} />}
                      title="Battery reserve"
                      value={current ? current.battery_soc_pct.toFixed(0) : "—"}
                      unit="%"
                      detail={
                        data.summary.battery_reserve_hours === null
                          ? "Reserve estimate unavailable while charging"
                          : `≈ ${data.summary.battery_reserve_hours}h at the present discharge rate`
                      }
                    />
                    <Metric
                      icon={<Plug size={19} />}
                      title="Grid availability"
                      value={
                        data.summary.grid_availability_pct?.toFixed(1) || "—"
                      }
                      unit="%"
                      detail={`${data.summary.coverage_pct.toFixed(1)}% telemetry coverage · ${hours}h window`}
                    />
                  </section>

                  <section className="panel energy-chart">
                    <div className="section-heading">
                      <div>
                        <h2>Energy through the day</h2>
                        <p>
                          Consumption and solar output across the last {hours}{" "}
                          hours.
                        </p>
                      </div>
                      <span className="small-label">kW · WAT</span>
                    </div>
                    <div
                      className="chart-container"
                      role="img"
                      aria-label="Line chart of electricity consumption and solar generation in kilowatts"
                    >
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart
                          data={chart}
                          margin={{ top: 10, right: 8, left: -22, bottom: 0 }}
                        >
                          <defs>
                            <linearGradient
                              id="solar-fill"
                              x1="0"
                              y1="0"
                              x2="0"
                              y2="1"
                            >
                              <stop
                                offset="0%"
                                stopColor="#8cbd51"
                                stopOpacity={0.27}
                              />
                              <stop
                                offset="100%"
                                stopColor="#8cbd51"
                                stopOpacity={0.02}
                              />
                            </linearGradient>
                          </defs>
                          <CartesianGrid
                            vertical={false}
                            stroke="#e9ede8"
                            strokeDasharray="3 4"
                          />
                          <XAxis
                            dataKey="timestamp"
                            type="number"
                            domain={["dataMin", "dataMax"]}
                            tickFormatter={time}
                            minTickGap={55}
                            axisLine={false}
                            tickLine={false}
                            tick={{ fill: "#78837b", fontSize: 11 }}
                          />
                          <YAxis
                            axisLine={false}
                            tickLine={false}
                            tick={{ fill: "#78837b", fontSize: 11 }}
                          />
                          <Tooltip
                            labelFormatter={(value) =>
                              `${date(new Date(Number(value)).toISOString())} · ${time(Number(value))} WAT`
                            }
                            formatter={(value, name) => [
                              `${Number(value).toFixed(2)} kW`,
                              name,
                            ]}
                            contentStyle={{
                              borderRadius: 8,
                              border: "1px solid #dde5dc",
                              fontSize: 12,
                            }}
                          />
                          <Legend
                            verticalAlign="top"
                            align="right"
                            iconType="circle"
                            iconSize={7}
                            wrapperStyle={{ paddingBottom: 18, fontSize: 12 }}
                          />
                          <Area
                            type="monotone"
                            dataKey="Solar"
                            stroke="#83ad49"
                            strokeWidth={2}
                            fill="url(#solar-fill)"
                            isAnimationActive={false}
                          />
                          <Area
                            type="monotone"
                            dataKey="Load"
                            stroke="#1b5141"
                            strokeWidth={2}
                            fill="transparent"
                            isAnimationActive={false}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="chart-footer">
                      <span>
                        <span className="status-dot" />
                        {data.series.length} observations
                      </span>
                      <span>
                        {data.summary.observed_hours.toFixed(1)} hours observed
                        · gaps excluded from energy totals
                      </span>
                    </div>
                  </section>

                  <div className="two-column">
                    <section className="panel flow-panel">
                      <div className="section-heading">
                        <div>
                          <h2>Power, right now</h2>
                          <p>A snapshot of your installation.</p>
                        </div>
                        <span
                          className={`badge ${gridDown ? "amber" : "green"}`}
                        >
                          {gridDown ? "Grid interrupted" : "Grid available"}
                        </span>
                      </div>
                      <div className="power-flow">
                        <div className="flow-node solar">
                          <Sun size={26} />
                          <span>Solar</span>
                          <strong>
                            {kw(current?.solar_w)} <small>kW</small>
                          </strong>
                        </div>
                        <span className="flow-connector" aria-hidden="true">
                          →
                        </span>
                        <div className="flow-node home">
                          <HouseLine size={29} />
                          <span>Consumption</span>
                          <strong>
                            {kw(current?.load_w)} <small>kW</small>
                          </strong>
                        </div>
                        <span className="flow-connector" aria-hidden="true">
                          ←
                        </span>
                        <div className="flow-node">
                          <BatteryCharging size={26} />
                          <span>Battery</span>
                          <strong>
                            {current ? current.battery_soc_pct.toFixed(0) : "—"}
                            <small>%</small>
                          </strong>
                        </div>
                      </div>
                      <div className="flow-detail">
                        <span>
                          <Plug size={17} />
                          Grid voltage
                        </span>
                        <strong>
                          {current?.grid_voltage_v.toFixed(0) || "—"} V
                        </strong>
                      </div>
                      <div className="flow-detail">
                        <span>
                          <BatteryCharging size={17} />
                          Battery power
                        </span>
                        <strong>
                          {kw(Math.abs(current?.battery_power_w || 0))} kW{" "}
                          <small>
                            {(current?.battery_power_w || 0) > 0
                              ? "discharging"
                              : "charging / idle"}
                          </small>
                        </strong>
                      </div>
                    </section>

                    <section className="panel forecast-panel">
                      <div className="section-heading">
                        <div>
                          <h2>The next six hours</h2>
                          <p>
                            Seasonal median forecast from recent observations.
                          </p>
                        </div>
                        <ChartLine size={22} />
                      </div>
                      {forecastChart.length ? (
                        <>
                          <div
                            className="forecast-chart"
                            role="img"
                            aria-label="Six-hour forecast of consumption and solar generation"
                          >
                            <ResponsiveContainer width="100%" height="100%">
                              <ComposedChart
                                data={forecastChart}
                                margin={{ top: 4, right: 3, left: -23 }}
                              >
                                <CartesianGrid
                                  vertical={false}
                                  stroke="#edf0eb"
                                  strokeDasharray="3 4"
                                />
                                <XAxis
                                  dataKey="timestamp"
                                  tickFormatter={time}
                                  minTickGap={35}
                                  axisLine={false}
                                  tickLine={false}
                                  tick={{ fontSize: 10, fill: "#78837b" }}
                                />
                                <YAxis
                                  axisLine={false}
                                  tickLine={false}
                                  tick={{ fontSize: 10, fill: "#78837b" }}
                                />
                                <Tooltip
                                  labelFormatter={(value) =>
                                    `${time(Number(value))} WAT`
                                  }
                                  formatter={(value, name) => [
                                    Array.isArray(value)
                                      ? `${value.map((number) => Number(number).toFixed(2)).join("–")} kW`
                                      : `${Number(value).toFixed(2)} kW`,
                                    name,
                                  ]}
                                />
                                <Area
                                  dataKey="range"
                                  name="Historical variation"
                                  stroke="none"
                                  fill="#dce8d5"
                                  isAnimationActive={false}
                                />
                                <Line
                                  dataKey="Load"
                                  stroke="#245644"
                                  strokeWidth={2}
                                  dot={false}
                                  strokeDasharray="5 4"
                                  isAnimationActive={false}
                                />
                                <Line
                                  dataKey="Solar"
                                  stroke="#8bad53"
                                  strokeWidth={2}
                                  dot={false}
                                  isAnimationActive={false}
                                />
                              </ComposedChart>
                            </ResponsiveContainer>
                          </div>
                          <p className="forecast-note">{prediction?.note}</p>
                          <div className="forecast-score">
                            <span>
                              Holdout MAE{" "}
                              <strong>
                                {prediction?.backtest
                                  ? `${prediction.backtest.mae_w.toFixed(0)} W`
                                  : "—"}
                              </strong>
                            </span>
                            <span>
                              Persistence baseline{" "}
                              <strong>
                                {prediction?.backtest
                                  ? `${prediction.backtest.persistence_mae_w.toFixed(0)} W`
                                  : "—"}
                              </strong>
                            </span>
                          </div>
                        </>
                      ) : (
                        <div className="inline-empty">
                          Collect at least 12 observations to generate a
                          forecast.
                        </div>
                      )}
                    </section>
                  </div>
                </>
              )}

              {tab !== "Devices" && (
                <section className="panel outages-panel">
                  <div className="section-heading">
                    <div>
                      <h2>Grid interruptions</h2>
                      <p>
                        Confirmed by two consecutive low-voltage observations.
                      </p>
                    </div>
                    <span className="badge neutral">
                      {data.outages.length} events
                    </span>
                  </div>
                  {data.outages.length ? (
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Started · WAT</th>
                            <th>Restored · WAT</th>
                            <th>Observed duration</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.outages
                            .slice(0, tab === "Outages" ? 30 : 4)
                            .map((outage) => (
                              <tr key={outage.started_at}>
                                <td>
                                  <span className="event-icon">
                                    <Plug size={15} />
                                  </span>
                                  {date(outage.started_at)}{" "}
                                  <span className="subtle">
                                    {time(outage.started_at)}
                                  </span>
                                </td>
                                <td>
                                  {outage.ongoing
                                    ? "Awaiting restoration"
                                    : outage.interrupted_by_gap
                                      ? "Telemetry gap"
                                      : `${date(outage.ended_at)} ${time(outage.ended_at)}`}
                                </td>
                                <td>{duration(outage.duration_minutes)}</td>
                                <td>
                                  <span
                                    className={`badge ${outage.ongoing ? "amber" : outage.interrupted_by_gap ? "neutral" : "green"}`}
                                  >
                                    {outage.ongoing
                                      ? "Ongoing"
                                      : outage.interrupted_by_gap
                                        ? "Uncertain end"
                                        : "Restored"}
                                  </span>
                                </td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="inline-empty">
                      <CheckCircle size={22} />
                      No confirmed interruptions in this window.
                    </div>
                  )}
                  <div className="panel-bottom">
                    <span>
                      Missing observations are treated as unknown coverage.
                    </span>
                    {tab === "Overview" && (
                      <button
                        className="text-button"
                        onClick={() => setTab("Outages")}
                      >
                        View all events <ArrowUpRight size={15} />
                      </button>
                    )}
                  </div>
                </section>
              )}

              {data.alerts.length > 0 && (
                <section className="alerts-strip" aria-label="Detected alerts">
                  <WarningCircle size={22} />
                  <div>
                    <strong>{data.alerts[0].message}</strong>
                    <p>
                      {data.alerts.length} alert
                      {data.alerts.length === 1 ? "" : "s"} in this window ·
                      latest at {time(data.alerts[0].recorded_at)} WAT
                    </p>
                  </div>
                </section>
              )}

              {(tab === "Devices" || tab === "Overview") && (
                <section className="panel edge-panel">
                  <div className="section-heading">
                    <div>
                      <h2>
                        <Database size={20} />
                        {demo ? "Try the offline edge" : "Device telemetry"}
                      </h2>
                      <p>
                        {demo
                          ? "Disconnect the uplink, collect a sample, then reconnect. Your queue survives a page reload."
                          : "Readings are authenticated per device and replayed by event ID."}
                      </p>
                    </div>
                    <span
                      className={`badge ${uplinkOffline ? "amber" : "green"}`}
                    >
                      {uplinkOffline ? (
                        <WifiSlash size={14} />
                      ) : (
                        <WifiHigh size={14} />
                      )}
                      {uplinkOffline
                        ? "Uplink disconnected"
                        : "Uplink available"}
                    </span>
                  </div>
                  <div className="edge-details">
                    <div>
                      <small>PRIMARY INVERTER</small>
                      <strong>{data.device_id || "Not provisioned"}</strong>
                    </div>
                    <div>
                      <small>LAST OBSERVATION</small>
                      <strong>
                        {data.last_seen
                          ? `${date(data.last_seen)}, ${time(data.last_seen)} WAT`
                          : "No observations"}
                      </strong>
                    </div>
                    <div>
                      <small>BROWSER OUTBOX</small>
                      <strong>
                        {queued} pending{" "}
                        <span className="subtle">readings</span>
                      </strong>
                    </div>
                  </div>
                  {demo && (
                    <div className="edge-actions">
                      <button
                        className="button"
                        disabled={busy}
                        onClick={() =>
                          void action(async () => {
                            const next = !uplinkOffline;
                            setUplinkOffline(next);
                            if (!next) await sync();
                            else
                              setNotice(
                                "Uplink paused for this demo. New samples will stay in the local outbox.",
                              );
                          })
                        }
                      >
                        {uplinkOffline ? (
                          <WifiHigh size={17} />
                        ) : (
                          <WifiSlash size={17} />
                        )}
                        {uplinkOffline
                          ? "Reconnect uplink"
                          : "Disconnect uplink"}
                      </button>
                      <button
                        className="button primary"
                        disabled={busy || !current}
                        onClick={() => void action(collect)}
                      >
                        <Database size={17} />
                        Collect sample
                      </button>
                      <button
                        className="button"
                        disabled={busy || uplinkOffline || !queued}
                        onClick={() => void action(sync)}
                      >
                        <ArrowsClockwise size={17} />
                        Sync queue
                      </button>
                    </div>
                  )}
                </section>
              )}

              {demo && (
                <section className="simulation-bar">
                  <div>
                    <Flask size={20} />
                    <div>
                      <strong>A working lab, without the hardware.</strong>
                      <span>All readings in this workspace are simulated.</span>
                    </div>
                  </div>
                  <div className="simulation-controls">
                    <label className="sr-only" htmlFor="scenario">
                      Simulation scenario
                    </label>
                    <select
                      id="scenario"
                      value={scenario}
                      onChange={(event) => setScenario(event.target.value)}
                    >
                      <option value="outage">Grid outage</option>
                      <option value="restore">Grid restoration</option>
                      <option value="load-spike">Load spike</option>
                      <option value="low-battery">Low battery</option>
                    </select>
                    <button
                      className="button"
                      disabled={busy}
                      onClick={() => void action(runScenario)}
                    >
                      Run scenario <ArrowUpRight size={15} />
                    </button>
                  </div>
                </section>
              )}
              <footer>
                <span>GridSense · Built for intermittent power.</span>
                <span>
                  {data.last_seen
                    ? `Last observation ${time(data.last_seen)} WAT`
                    : "Waiting for observations"}
                  <span className="heading-dot">·</span>
                  {paused
                    ? "Live updates paused"
                    : "Refreshes every 20 seconds"}
                </span>
              </footer>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function Metric({
  icon,
  title,
  value,
  unit,
  detail,
  accent = false,
}: {
  icon: React.ReactNode;
  title: string;
  value: string;
  unit: string;
  detail: string;
  accent?: boolean;
}) {
  return (
    <article className={`metric ${accent ? "accent" : ""}`}>
      <div className="metric-title">
        {title}
        {icon}
      </div>
      <div className="metric-value">
        {value}
        <span>{unit}</span>
      </div>
      <p>{detail}</p>
    </article>
  );
}
