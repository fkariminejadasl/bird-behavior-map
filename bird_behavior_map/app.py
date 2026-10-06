"""
GPS burst explorer and simple relabeling app.

Data columns, in order:
    device_id, date_time, index, gt_label, imu_x, imu_y, imu_z,
    gps_speed, label, confidence, latitude, longitude, altitude

Notes:
    - If altitude is missing, it is filled with -1.
    - A GPS burst is identified by the unique pair: device_id + date_time.
    - Each burst is expected to contain 20 IMU rows.
    - The map shows one point per burst.
    - Relabeling writes a complete updated CSV to OUTPUT_FILE.

The data is made by bird_behavior_map/make_data.py.

Run: python -m bird_behavior_map.app <input_csv> [port]
"""

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, ctx, dcc, html, no_update

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# To run the app: python -m bird_behavior_map.app <input_csv> [port]
if len(sys.argv) < 2:
    sys.exit("Usage: python -m bird_behavior_map.app <input_csv> [port]")
GIMU_BEH_FILE = Path(sys.argv[1])
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8050

# A full copy of the data is written here after each relabel action.
# It keeps the same no-header CSV format as the input file.
OUTPUT_FILE = GIMU_BEH_FILE.with_name(f"{GIMU_BEH_FILE.stem}_relabelled.csv")

# Optional audit trail: one row per relabel action.
CHANGE_LOG_FILE = GIMU_BEH_FILE.with_name(f"{GIMU_BEH_FILE.stem}_label_changes.csv")

LABEL_MODE = "day"  # or "month"
PREDICTION_GLEN = 20

# Behavior labels and colors.
ind2name = {
    0: "Flap",
    1: "ExFlap",
    2: "Soar",
    3: "Boat",
    4: "Float",
    5: "SitStand",
    6: "TerLoco",
    7: "Other",
    8: "Manouvre",
    9: "Pecking",
}

ind2color = {
    0: "#1f77b4",
    1: "#aec7e8",
    2: "#ff7f0e",
    3: "#ffbb78",
    4: "#2ca02c",
    5: "#98df8a",
    6: "#d62728",
    7: "#7f7f7f",
    8: "#9467bd",
    9: "#c5b0d5",
}

COLS = [
    "device_id",
    "date_time",
    "index",
    "gt_label",
    "imu_x",
    "imu_y",
    "imu_z",
    "gps_speed",
    "label",
    "confidence",
    "latitude",
    "longitude",
    "altitude",
]

# -----------------------------------------------------------------------------
# Data loading and burst table creation
# -----------------------------------------------------------------------------


def load_data(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, header=None)

    if raw.shape[1] < 12:
        raise ValueError(
            "Expected at least 12 columns: device_id through longitude. "
            f"Found {raw.shape[1]} columns."
        )

    # If altitude is missing, fake it as -1 for all rows.
    if raw.shape[1] == 12:
        raw[12] = -1

    # Ignore extra columns if present, then assign names.
    raw = raw.iloc[:, :13].copy()
    raw.columns = COLS

    raw["date_time"] = pd.to_datetime(raw["date_time"])
    raw["label"] = raw["label"].astype(int)
    raw["gt_label"] = raw["gt_label"].astype(int)
    raw = raw.sort_values(["device_id", "date_time", "index"]).reset_index(drop=True)
    return raw


def build_burst_df(raw: pd.DataFrame) -> pd.DataFrame:
    def block_values(series: pd.Series) -> list:
        return series.iloc[::PREDICTION_GLEN].tolist()

    def block_label_text(series: pd.Series) -> str:
        return ", ".join(
            ind2name.get(int(label_id), str(label_id))
            for label_id in block_values(series)
        )

    def block_gt_text(series: pd.Series) -> str:
        names = []
        for label_id in block_values(series):
            label_id = int(label_id)
            names.append(
                "None" if label_id == -1 else ind2name.get(label_id, str(label_id))
            )
        return ", ".join(names)

    def block_confidence_text(series: pd.Series) -> str:
        return ", ".join(f"{float(conf):.3f}" for conf in block_values(series))

    b = (
        raw.groupby(["device_id", "date_time"], sort=True)
        .agg(
            latitude=("latitude", "first"),
            longitude=("longitude", "first"),
            gps_speed=("gps_speed", "first"),
            label=("label", "first"),
            confidence=("confidence", "first"),
            altitude=("altitude", "first"),
            gt_label=("gt_label", "first"),
            label_name=("label", block_label_text),
            gt_label_name=("gt_label", block_gt_text),
            confidence_text=("confidence", block_confidence_text),
            row_start=("index", "idxmin"),
            n_imu=("index", "size"),
        )
        .reset_index()
        .sort_values(["device_id", "date_time"])
        .reset_index(drop=True)
    )
    b["burst_id"] = b.index.astype(int)
    b["device_id_str"] = b["device_id"].astype(str)
    return b


df_all = load_data(GIMU_BEH_FILE)
burst_df = build_burst_df(df_all)
df_all = df_all.merge(
    burst_df[["device_id", "date_time", "burst_id"]],
    on=["device_id", "date_time"],
    how="left",
)

DEVICE_IDS = sorted(burst_df["device_id"].unique().tolist())
DEFAULT_DEVICE = DEVICE_IDS[0]
CLASS_KEYS = sorted(ind2name.keys())

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def ts_to_epoch_seconds(ts: pd.Timestamp) -> int:
    return int(ts.replace(tzinfo=timezone.utc).timestamp())


def epoch_seconds_to_str(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def label_text(label_id) -> str:
    try:
        label_id = int(label_id)
    except (TypeError, ValueError):
        return str(label_id)
    return ind2name.get(label_id, str(label_id))


def gt_text(gt_label) -> str:
    try:
        gt_label = int(gt_label)
    except (TypeError, ValueError):
        return "None"
    if gt_label == -1:
        return "None"
    return ind2name.get(gt_label, str(gt_label))


def repeated_label_text(label_id, n_rows) -> str:
    n_blocks = max(1, math.ceil(int(n_rows) / PREDICTION_GLEN))
    return ", ".join([label_text(label_id)] * n_blocks)


def mk_marks(ts: pd.Series, max_marks: int = 12) -> dict[int, str]:
    ts_full = ts.sort_values().dt.floor("s").drop_duplicates()

    if LABEL_MODE == "month":
        ts_norm = ts_full.dt.to_period("M").dt.start_time.drop_duplicates()
        fmt = "%Y-%m"
    else:
        ts_norm = ts_full.dt.normalize().drop_duplicates()
        fmt = "%Y-%m-%d"

    if len(ts_norm) > max_marks:
        step = max(1, len(ts_norm) // (max_marks - 1))
        ts_norm = ts_norm[::step]

    endpoints = pd.Series([ts_full.iloc[0], ts_full.iloc[-1]])
    ts_marks = (
        pd.concat([pd.Series(ts_norm), endpoints]).drop_duplicates().sort_values()
    )
    return {ts_to_epoch_seconds(t): t.strftime(fmt) for t in ts_marks}


def get_device_bursts(device_id) -> pd.DataFrame:
    return burst_df[burst_df["device_id"] == device_id].copy()


def get_selection_bursts(selection: dict | None) -> pd.DataFrame:
    if not selection or selection.get("start") is None or selection.get("end") is None:
        return burst_df.iloc[0:0].copy()

    start_id = int(selection["start"])
    end_id = int(selection["end"])
    start_row = burst_df.loc[burst_df["burst_id"] == start_id]
    end_row = burst_df.loc[burst_df["burst_id"] == end_id]
    if start_row.empty or end_row.empty:
        return burst_df.iloc[0:0].copy()

    device_id = start_row.iloc[0]["device_id"]
    if end_row.iloc[0]["device_id"] != device_id:
        return burst_df.iloc[0:0].copy()

    lo, hi = sorted([start_id, end_id])
    selected = burst_df[
        (burst_df["device_id"] == device_id)
        & (burst_df["burst_id"] >= lo)
        & (burst_df["burst_id"] <= hi)
    ].copy()
    return selected.sort_values("burst_id")


def map_center_zoom(dff: pd.DataFrame) -> tuple[dict, float]:
    if dff.empty:
        return {"lat": 0, "lon": 0}, 1

    west, east = float(dff.longitude.min()), float(dff.longitude.max())
    south, north = float(dff.latitude.min()), float(dff.latitude.max())
    center = {"lat": (south + north) / 2.0, "lon": (west + east) / 2.0}
    span = max(east - west, north - south, 1e-6)
    zoom = max(0, 8 - math.log2(span)) + 2
    return center, zoom


def make_empty_fig(title: str, height: int = 260) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=title,
        height=height,
        margin=dict(l=45, r=20, t=45, b=40),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text="No data selected",
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=14),
            )
        ],
    )
    return fig


def make_map_figure(
    dff: pd.DataFrame,
    selection: dict | None = None,
    style: str = "open-street-map",
    height: int = 650,
) -> go.Figure:
    center, zoom = map_center_zoom(dff)
    traces = []

    traces.append(
        go.Scattermap(
            lat=dff["latitude"],
            lon=dff["longitude"],
            mode="lines",
            name="Path",
            line=dict(width=1, color="rgba(0,0,0,0.35)"),
            hoverinfo="skip",
        )
    )

    # One marker trace per label to preserve the previous legend behavior.
    for k in CLASS_KEYS:
        sub = dff[dff["label"] == k].copy()
        if sub.empty:
            lat_vals = [None]
            lon_vals = [None]
            customdata = None
        else:
            lat_vals = sub["latitude"]
            lon_vals = sub["longitude"]
            customdata = np.stack(
                [
                    sub["burst_id"],
                    sub["device_id"],
                    sub["date_time"].dt.strftime("%Y-%m-%d %H:%M:%S"),
                    sub["label"],
                    sub["label_name"],
                    sub["confidence"],
                    sub["gt_label"],
                    sub["gt_label_name"],
                    sub["gps_speed"],
                    sub["altitude"],
                    sub["n_imu"],
                    sub["confidence_text"],
                ],
                axis=-1,
            )

        traces.append(
            go.Scattermap(
                lat=lat_vals,
                lon=lon_vals,
                mode="markers",
                name=ind2name.get(k, str(k)),
                marker=dict(size=6, color=ind2color.get(k, "#444")),
                customdata=customdata,
                hovertemplate=(
                    "date_time: %{customdata[2]}<br>"
                    "pred: %{customdata[4]}<br>"
                    "gt: %{customdata[7]}<br>"
                    "confidence: %{customdata[11]}<extra></extra>"
                ),
                showlegend=True,
            )
        )

    selected = get_selection_bursts(selection)
    if not selected.empty:
        traces.append(
            go.Scattermap(
                lat=selected["latitude"],
                lon=selected["longitude"],
                mode="markers",
                name="Selected region",
                marker=dict(size=12, color="rgba(0,0,0,0.22)"),
                hoverinfo="skip",
                showlegend=True,
            )
        )

    # Highlight selection start and end points.
    marker_points = []
    for key_name, label_name in (
        ("start", "Selection start"),
        ("end", "Selection end"),
    ):
        if selection and selection.get(key_name) is not None:
            row = burst_df[burst_df["burst_id"] == int(selection[key_name])]
            if not row.empty:
                marker_points.append((label_name, row.iloc[0]))

    for label_name, row in marker_points:
        traces.append(
            go.Scattermap(
                lat=[row["latitude"]],
                lon=[row["longitude"]],
                mode="markers",
                name=label_name,
                marker=dict(size=18, color="black", symbol="circle"),
                hovertemplate=f"{label_name}<br>{row['date_time']}<extra></extra>",
                showlegend=True,
            )
        )

    fig = go.Figure(traces)
    fig.update_layout(
        map=dict(style=style, center=center, zoom=zoom),
        height=height,
        margin=dict(t=0, r=0, b=0, l=0),
        hovermode="closest",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        uirevision="keep",
    )
    return fig


def make_imu_figure(selected_burst: dict | None, height: int = 620) -> go.Figure:
    if not selected_burst:
        return make_empty_fig("IMU burst", height=height)

    burst_id = int(selected_burst["burst_id"])
    g = df_all[df_all["burst_id"] == burst_id].sort_values("index")
    if g.empty:
        return make_empty_fig("IMU burst", height=height)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=g["index"],
            y=g["imu_x"],
            mode="lines+markers",
            name="IMU X",
            line=dict(width=1.5, color="red"),
            marker=dict(size=5, symbol="star", color="red"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=g["index"],
            y=g["imu_y"],
            mode="lines+markers",
            name="IMU Y",
            line=dict(width=1.5, color="blue"),
            marker=dict(size=5, symbol="star", color="blue"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=g["index"],
            y=g["imu_z"],
            mode="lines+markers",
            name="IMU Z",
            line=dict(width=1.5, color="green"),
            marker=dict(size=5, symbol="star", color="green"),
        )
    )
    fig.add_hline(y=0, line_width=1, line_color="black")
    fig.update_layout(
        title="IMU burst",
        height=height,
        margin=dict(l=45, r=20, t=45, b=55),
        yaxis=dict(range=[-3.5, 3.5], tickmode="array", tickvals=[-3.5, 0, 3.5]),
        xaxis_title="IMU index within burst",
        yaxis_title="IMU value",
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5),
        uirevision="keep",
    )
    return fig


def extract_hover_burst_id(hover_data: dict | None) -> int | None:
    if not hover_data or not hover_data.get("points"):
        return None
    point = hover_data["points"][0]
    customdata = point.get("customdata")
    if customdata is None:
        return None
    try:
        return int(customdata[0])
    except (TypeError, ValueError, IndexError):
        return None


def make_series_figure(
    selected: pd.DataFrame,
    y_col: str,
    title: str,
    y_title: str,
    hover_burst_id: int | None = None,
) -> go.Figure:
    if selected.empty:
        return make_empty_fig(title, height=260)

    y = selected[y_col]
    fig = go.Figure()
    customdata = np.stack(
        [
            selected["burst_id"],
            selected["label_name"],
            selected["gt_label_name"],
            selected["confidence_text"],
        ],
        axis=-1,
    )
    fig.add_trace(
        go.Scatter(
            x=selected["date_time"],
            y=y,
            mode="lines+markers",
            name=y_title,
            customdata=customdata,
            hovertemplate=(
                "date_time: %{x}<br>"
                f"{y_title}: " + "%{y}<br>"
                "pred: %{customdata[1]}<br>"
                "gt: %{customdata[2]}<br>"
                "confidence: %{customdata[3]}<extra></extra>"
            ),
        )
    )

    if hover_burst_id is not None and hover_burst_id in set(
        selected["burst_id"].tolist()
    ):
        h = selected[selected["burst_id"] == hover_burst_id].iloc[0]
        fig.add_vline(
            x=h["date_time"], line_width=2, line_dash="dot", line_color="black"
        )
        fig.add_trace(
            go.Scatter(
                x=[h["date_time"]],
                y=[h[y_col]],
                mode="markers",
                name="Hovered burst",
                marker=dict(size=13, color="black"),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    fig.update_layout(
        title=title,
        height=260,
        margin=dict(l=55, r=20, t=45, b=40),
        xaxis_title="date_time",
        yaxis_title=y_title,
        hovermode="closest",
        uirevision="keep",
    )
    return fig


def click_to_burst(click_data: dict | None) -> dict | None:
    if not click_data or not click_data.get("points"):
        return None
    point = click_data["points"][0]
    customdata = point.get("customdata")
    if customdata is None:
        return None

    try:
        return {
            "burst_id": int(customdata[0]),
            "device_id": int(customdata[1]),
            "date_time": str(customdata[2]),
            "label": int(customdata[3]),
            "label_name": str(customdata[4]),
            "confidence": float(customdata[5]),
            "gt_label": int(customdata[6]),
            "gt_label_name": str(customdata[7]),
            "gps_speed": float(customdata[8]),
            "altitude": float(customdata[9]),
            "n_imu": int(customdata[10]),
        }
    except (TypeError, ValueError, IndexError):
        return None


def save_relabelled_data(output_file: Path = OUTPUT_FILE) -> None:
    """Save the full current dataset in the same no-header CSV format as the input."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df_all[COLS].to_csv(
        output_file,
        header=False,
        index=False,
        date_format="%Y-%m-%d %H:%M:%S",
    )


def append_change_log(selected: pd.DataFrame, new_label: int) -> None:
    """Append one compact audit row for each relabel action."""
    CHANGE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame(
        [
            {
                "changed_at_utc": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "device_id": selected.iloc[0]["device_id"],
                "start_date_time": selected.iloc[0]["date_time"],
                "end_date_time": selected.iloc[-1]["date_time"],
                "start_burst_id": int(selected.iloc[0]["burst_id"]),
                "end_burst_id": int(selected.iloc[-1]["burst_id"]),
                "new_label": int(new_label),
                "new_label_name": ind2name.get(int(new_label), str(new_label)),
                "n_bursts": int(len(selected)),
                "n_raw_rows": int(selected["n_imu"].sum()),
                "output_file": str(OUTPUT_FILE),
            }
        ]
    )
    row.to_csv(
        CHANGE_LOG_FILE,
        mode="a",
        header=not CHANGE_LOG_FILE.exists(),
        index=False,
        date_format="%Y-%m-%d %H:%M:%S",
    )


def make_imu_metadata(selected_burst: dict | None):
    if not selected_burst:
        return "Click a GPS burst to inspect its IMU data."

    burst_id = int(selected_burst["burst_id"])
    row_df = burst_df.loc[burst_df["burst_id"] == burst_id]
    if row_df.empty:
        return "Selected burst was not found."

    row = row_df.iloc[0]
    pred = row["label_name"]
    gt = row["gt_label_name"]
    mismatch = ""
    if int(row["gt_label"]) != -1 and int(row["gt_label"]) != int(row["label"]):
        mismatch = " | mismatch"

    return html.Div(
        style={
            "padding": "8px 10px",
            "marginBottom": "6px",
            "border": "1px solid #ddd",
            "borderRadius": "6px",
            "background": "#fafafa",
            "fontSize": "13px",
            "lineHeight": "1.45",
        },
        children=[
            html.Div(f"Device: {row['device_id']}"),
            html.Div(f"Date time: {row['date_time']}"),
            html.Div(
                f"Pred: {pred} | GT: {gt} | Confidence: {row['confidence_text']}{mismatch}"
            ),
            html.Div(
                f"GPS speed: {row['gps_speed']:.3f} | Altitude: {row['altitude']} | IMU rows: {int(row['n_imu'])}"
            ),
        ],
    )


# -----------------------------------------------------------------------------
# Dash app
# -----------------------------------------------------------------------------

app = Dash(__name__)

# Hide the slider's numeric handle tooltip bubble.
app.index_string = """<!DOCTYPE html>
<html>
  <head>
    {%metas%}
    <title>{%title%}</title>
    {%favicon%}
    {%css%}
    <style>
      .rc-slider-tooltip{display:none !important;}
      button, select { font-size: 14px; }
      .main-row { display: flex; gap: 12px; align-items: stretch; }
      .map-pane { flex: 1 1 68%; min-width: 0; }
      .imu-pane { flex: 0 0 32%; min-width: 360px; }
      @media (max-width: 950px) {
        .main-row { flex-direction: column; }
        .imu-pane { min-width: 0; }
      }
    </style>
  </head>
  <body>
    {%app_entry%}
    <footer>
      {%config%}
      {%scripts%}
      {%renderer%}
    </footer>
  </body>
</html>"""

label_options = [{"label": f"{k}: {v}", "value": k} for k, v in ind2name.items()]
device_options = [{"label": str(d), "value": d} for d in DEVICE_IDS]

t_min = ts_to_epoch_seconds(burst_df["date_time"].min())
t_max = ts_to_epoch_seconds(burst_df["date_time"].max())

app.layout = html.Div(
    style={"padding": "12px", "fontFamily": "system-ui, sans-serif"},
    children=[
        dcc.Store(id="selected-burst", data=None),
        dcc.Store(id="selection", data={"start": None, "end": None}),
        dcc.Store(id="label-version", data=0),
        html.Div(
            style={
                "display": "flex",
                "gap": "14px",
                "alignItems": "center",
                "flexWrap": "wrap",
            },
            children=[
                html.Div(
                    children=[
                        html.Label(
                            "Bird/device", style={"display": "block", "fontWeight": 600}
                        ),
                        dcc.Dropdown(
                            id="device-dropdown",
                            options=device_options,
                            value=DEFAULT_DEVICE,
                            clearable=False,
                            style={"width": "160px"},
                        ),
                    ]
                ),
                html.Div(
                    children=[
                        html.Label(
                            "Click mode", style={"display": "block", "fontWeight": 600}
                        ),
                        dcc.RadioItems(
                            id="click-mode",
                            options=[
                                {"label": "Inspect point", "value": "inspect"},
                                {"label": "Select region", "value": "select"},
                            ],
                            value="inspect",
                            inline=True,
                            inputStyle={"marginLeft": "8px", "marginRight": "4px"},
                        ),
                    ]
                ),
                html.Button("Clear selection", id="clear-selection", n_clicks=0),
                html.Div(id="click-status", style={"fontWeight": 600}),
            ],
        ),
        html.Div(
            className="main-row",
            children=[
                html.Div(
                    className="map-pane",
                    children=[
                        dcc.Graph(id="map-graph", config={"scrollZoom": True}),
                        html.Div("Time window", style={"padding": "8px 4px 0 4px"}),
                        dcc.RangeSlider(
                            id="time-slider",
                            min=t_min,
                            max=t_max,
                            step=1,
                            allowCross=False,
                            value=[t_min, t_max],
                            marks=mk_marks(burst_df["date_time"]),
                            tooltip={"always_visible": False, "placement": "bottom"},
                        ),
                        html.Div(
                            id="time-readout",
                            style={"marginTop": "6px", "opacity": 0.7},
                        ),
                    ],
                ),
                html.Div(
                    className="imu-pane",
                    children=[
                        html.Div(id="imu-meta"),
                        dcc.Graph(id="imu-graph"),
                    ],
                ),
            ],
        ),
        html.Div(
            style={
                "display": "flex",
                "gap": "12px",
                "alignItems": "end",
                "flexWrap": "wrap",
            },
            children=[
                html.Div(
                    children=[
                        html.Label(
                            "New label for selected region",
                            style={"display": "block", "fontWeight": 600},
                        ),
                        dcc.Dropdown(
                            id="new-label",
                            options=label_options,
                            value=0,
                            clearable=False,
                            style={"width": "220px"},
                        ),
                    ]
                ),
                html.Button(
                    "Apply label to selected region", id="apply-label", n_clicks=0
                ),
                html.Div(id="apply-status", style={"fontWeight": 600}),
            ],
        ),
        html.Div(id="selection-info", style={"marginTop": "6px", "opacity": 0.85}),
        dcc.Graph(id="altitude-graph", clear_on_unhover=False),
        dcc.Graph(id="speed-graph", clear_on_unhover=False),
    ],
)


@app.callback(
    Output("selection", "data", allow_duplicate=True),
    Output("selected-burst", "data", allow_duplicate=True),
    Output("click-status", "children"),
    Input("map-graph", "clickData"),
    Input("clear-selection", "n_clicks"),
    State("click-mode", "value"),
    State("selection", "data"),
    State("device-dropdown", "value"),
    prevent_initial_call=True,
)
def handle_map_click(click_data, _clear_clicks, mode, selection, device_id):
    trig = ctx.triggered_id

    if trig == "clear-selection":
        return {"start": None, "end": None}, None, "Selection cleared."

    clicked = click_to_burst(click_data)
    if clicked is None:
        return no_update, no_update, no_update

    if clicked["device_id"] != device_id:
        return (
            no_update,
            no_update,
            "Click ignored because it is not from the selected bird/device.",
        )

    if mode == "inspect":
        msg = f"Inspecting burst {clicked['burst_id']} at {clicked['date_time']}."
        return no_update, clicked, msg

    # Select-region mode: first click sets start, second click sets end.
    selection = selection or {"start": None, "end": None}
    if selection.get("start") is None or selection.get("end") is not None:
        new_selection = {"start": clicked["burst_id"], "end": None}
        msg = f"Selection start set to {clicked['date_time']}. Click an end point."
        return new_selection, clicked, msg

    start_id = int(selection["start"])
    start_device = int(
        burst_df.loc[burst_df["burst_id"] == start_id, "device_id"].iloc[0]
    )
    if clicked["device_id"] != start_device:
        return (
            selection,
            clicked,
            "Start and end must be from the same bird/device. Selection was not changed.",
        )

    new_selection = {"start": start_id, "end": clicked["burst_id"]}
    selected = get_selection_bursts(new_selection)
    msg = f"Selected {len(selected)} bursts from one bird/device."
    return new_selection, clicked, msg


@app.callback(
    Output("map-graph", "figure"),
    Output("time-readout", "children"),
    Input("time-slider", "value"),
    Input("device-dropdown", "value"),
    Input("selection", "data"),
    Input("label-version", "data"),
)
def update_map(selected_range, device_id, selection, _label_version):
    start_s, end_s = selected_range
    start = pd.to_datetime(epoch_seconds_to_str(start_s))
    end = pd.to_datetime(epoch_seconds_to_str(end_s))

    dff = get_device_bursts(device_id)
    mask = (dff["date_time"] >= start) & (dff["date_time"] <= end)
    dff = dff.loc[mask].copy()

    fig = make_map_figure(dff, selection=selection)
    txt = (
        f"Showing bird/device {device_id}: {start} to {end} "
        f"(visible bursts: {len(dff)}, raw rows represented: {int(dff['n_imu'].sum()) if not dff.empty else 0})"
    )
    return fig, txt


@app.callback(
    Output("imu-meta", "children"),
    Output("imu-graph", "figure"),
    Input("selected-burst", "data"),
    Input("label-version", "data"),
)
def update_imu(selected_burst, _label_version):
    return make_imu_metadata(selected_burst), make_imu_figure(selected_burst)


@app.callback(
    Output("altitude-graph", "figure"),
    Output("speed-graph", "figure"),
    Output("selection-info", "children"),
    Input("selection", "data"),
    Input("altitude-graph", "hoverData"),
    Input("speed-graph", "hoverData"),
    Input("label-version", "data"),
)
def update_selection_plots(selection, altitude_hover, speed_hover, _label_version):
    selected = get_selection_bursts(selection)
    hover_id = extract_hover_burst_id(altitude_hover) or extract_hover_burst_id(
        speed_hover
    )

    alt_fig = make_series_figure(
        selected,
        y_col="altitude",
        title="Selected region altitude",
        y_title="altitude",
        hover_burst_id=hover_id,
    )
    speed_fig = make_series_figure(
        selected,
        y_col="gps_speed",
        title="Selected region GPS speed",
        y_title="gps_speed",
        hover_burst_id=hover_id,
    )

    if selected.empty:
        info = "No complete selected region yet. Use Select region mode and click start and end points."
    else:
        info = (
            f"Selected bird/device {selected.iloc[0]['device_id']}: "
            f"{selected.iloc[0]['date_time']} to {selected.iloc[-1]['date_time']} "
            f"({len(selected)} bursts, {int(selected['n_imu'].sum())} raw IMU rows)."
        )
    return alt_fig, speed_fig, info


@app.callback(
    Output("apply-status", "children"),
    Output("label-version", "data"),
    Input("apply-label", "n_clicks"),
    State("selection", "data"),
    State("new-label", "value"),
    State("label-version", "data"),
    prevent_initial_call=True,
)
def apply_label(_n_clicks, selection, new_label, label_version):
    global df_all, burst_df

    selected = get_selection_bursts(selection)
    if selected.empty:
        return "No complete selected region to relabel.", no_update

    new_label = int(new_label)
    selected_ids = set(selected["burst_id"].tolist())

    # Update the raw rows and the burst table in memory.
    df_all.loc[df_all["burst_id"].isin(selected_ids), "label"] = new_label
    burst_df.loc[burst_df["burst_id"].isin(selected_ids), "label"] = new_label
    burst_df.loc[burst_df["burst_id"].isin(selected_ids), "label_name"] = burst_df.loc[
        burst_df["burst_id"].isin(selected_ids), "n_imu"
    ].apply(lambda n_rows: repeated_label_text(new_label, n_rows))

    try:
        save_relabelled_data()
        append_change_log(selected, new_label)
    except OSError as exc:
        return (
            f"Applied label in memory, but could not save the file: {exc}",
            int(label_version or 0) + 1,
        )

    return (
        f"Applied label {new_label}: {ind2name.get(new_label, str(new_label))} "
        f"to {len(selected)} bursts and {int(selected['n_imu'].sum())} raw rows. "
        f"Saved full updated CSV to: {OUTPUT_FILE}",
        int(label_version or 0) + 1,
    )


if __name__ == "__main__":
    app.run(debug=True, port=port)
