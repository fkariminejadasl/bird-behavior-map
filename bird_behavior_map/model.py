"""The trained behavior classifier.

Copied from bird-behavior: the network `BirdModelSmallDilated` from
`behavior/model.py`, `add_magnitude_features` and the speed scaling of
`BirdDataset` from `behavior/data.py`, `inference` from `behavior/utils.py`
and `infer_update_classes` from `behavior/model_utils.py`. The weights are
those of its experiment 197, in `models/197_best.pth`. The same copy lives in
gulliver-behavior-classifier.

One burst is 20 accelerometer samples (x, y, z in g) plus the GPS speed of its
fix in m/s. The network reads 7 channels, those four and three magnitude
channels, and gives one of 9 classes per burst.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

CHECKPOINT = Path(__file__).parent / "models" / "197_best.pth"
GLEN = 20  # samples per burst
GPS_SPEED_SCALE = 22.3012351755624  # the training data was divided by this
BATCH_SIZE = 4096

# Label -> class name, as in the app CSV. 7 (Other) is not a model class.
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

# Model output index -> label.
MODEL_LABELS = [0, 1, 2, 3, 4, 5, 6, 8, 9]


class BirdModelSmallDilated(nn.Module):
    def __init__(self, in_channels=7, mid_channels=20, out_channels=9, dropout=0.15):
        super().__init__()

        self.net = nn.Sequential(
            nn.Conv1d(in_channels, mid_channels, kernel_size=5, padding=2, dilation=1),
            nn.GroupNorm(4, mid_channels),
            nn.GELU(),
            nn.Conv1d(mid_channels, mid_channels, kernel_size=5, padding=4, dilation=2),
            nn.GroupNorm(4, mid_channels),
            nn.GELU(),
            nn.Conv1d(mid_channels, mid_channels, kernel_size=5, padding=6, dilation=3),
            nn.GroupNorm(4, mid_channels),
            nn.GELU(),
        )

        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(mid_channels * 3, out_channels)

    def forward(self, x):
        x = self.net(x)
        x = torch.cat(
            [
                x.mean(dim=-1),
                x.amax(dim=-1),
                x.std(dim=-1, unbiased=False),
            ],
            dim=1,
        )
        return self.fc(self.dropout(x))


def add_magnitude_features(data: np.ndarray) -> np.ndarray:
    """N x L x 4 (acceleration x, y, z, GPS speed) -> N x L x 7.

    The three added channels are norms of an acceleration vector, so a
    rotation of the whole burst leaves them alone:

      mag      total acceleration whatever its direction, about 1 g when the
               bird is still, because only gravity is left.
      dyn_mag  what is left after the static part (gravity and posture) is
               removed: VeDBA (Vectorial Dynamic Body Acceleration) over the
               mean of the burst.
      jerk_mag how abruptly the acceleration changes, per sample. It is
               undefined at the first sample and repeats the second one there.
    """
    acc = data[:, :, :3]
    mag = np.linalg.norm(acc, axis=2)
    dyn_mag = np.linalg.norm(acc - acc.mean(axis=1, keepdims=True), axis=2)
    jerk_mag = np.linalg.norm(np.diff(acc, axis=1), axis=2)  # L-1 long
    jerk_mag = np.concatenate([jerk_mag[:, :1], jerk_mag], axis=1)  # edge-replicate
    return np.concatenate([data, np.stack([mag, dyn_mag, jerk_mag], axis=2)], axis=2)


def load_model(checkpoint: str | Path = CHECKPOINT, device=None) -> nn.Module:
    """Build the network and load the trained weights into it."""
    if device is None:
        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = BirdModelSmallDilated()
    state = torch.load(checkpoint, map_location=device, weights_only=True)
    model.load_state_dict(state["model"])
    model.to(device)
    model.eval()
    return model


def model_input(bursts: np.ndarray) -> np.ndarray:
    """N x L x 4 bursts (x, y, z, GPS speed) -> N x 7 x L, what the network reads.

    The steps and their order are those of bird-behavior
    `behavior/data.py::BirdDataset`.
    """
    data = add_magnitude_features(bursts.astype(np.float64))  # N x L x 7
    data[:, :, 3] /= GPS_SPEED_SCALE
    return np.ascontiguousarray(data.transpose(0, 2, 1), dtype=np.float32)


def predict(
    model: nn.Module, bursts: np.ndarray, batch_size: int = BATCH_SIZE
) -> tuple[np.ndarray, np.ndarray]:
    """One label and its probability per burst (N x L x 4)."""
    device = next(model.parameters()).device
    labels = np.empty(len(bursts), dtype=np.int64)
    confidence = np.empty(len(bursts), dtype=np.float32)
    for start in range(0, len(bursts), batch_size):
        end = start + batch_size
        x = torch.from_numpy(model_input(bursts[start:end])).to(device)
        with torch.no_grad():
            logits = model(x)
        probabilities = torch.softmax(logits, dim=-1)
        best = torch.argmax(logits, dim=1)
        labels[start:end] = [MODEL_LABELS[i] for i in best.tolist()]
        confidence[start:end] = (
            probabilities.gather(1, best[:, None])[:, 0].cpu().numpy()
        )
    return labels, confidence


def classify(df: pd.DataFrame, model: nn.Module, glen: int = GLEN) -> pd.DataFrame:
    """Fill columns 8 (label) and 9 (confidence) of an app-format DataFrame.

    Every `glen` consecutive rows are one burst. Columns 4 to 7 are x, y, z
    and GPS speed. The columns are numbered as `pd.read_csv(..., header=None)`
    gives them.
    """
    if len(df) % glen != 0:
        raise ValueError(f"{len(df)} rows is not a multiple of {glen}")
    bursts = df[[4, 5, 6, 7]].to_numpy(dtype=np.float64).reshape(-1, glen, 4)
    labels, confidence = predict(model, bursts)
    df = df.copy()
    df[8] = np.repeat(labels, glen)
    df[9] = np.repeat(confidence, glen)
    return df
