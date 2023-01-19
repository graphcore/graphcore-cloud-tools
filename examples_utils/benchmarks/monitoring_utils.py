# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
from typing import List, Dict
from pathlib import Path
import json

try:
    import pandas as pd

    # while not used explicitely need to check
    from matplotlib import pyplot as plt
except (ImportError, ModuleNotFoundError) as error:
    from . import _incorrect_requirement_variant_error

    raise _incorrect_requirement_variant_error from error


def process_monitoring_file(file):
    file_content: List[Dict[str, Dict]] = [json.loads(l) for l in file.read_text().splitlines()]
    for entry in file_content:
        for i, card in enumerate(entry.pop("cards")):
            entry[f"cards.{i}"] = card
            for j, ipu in enumerate(card.pop("ipus")):
                card[f"ipus.{j}"] = ipu
    df = pd.json_normalize(file_content)
    pid_columns = [c for c in df.columns if ".PID" in c]
    df["ipus_in_use"] = df[pid_columns].notna().sum(axis="columns")
    df = df.set_index(pd.to_datetime(df["timestamp"], format="%Y-%m-%d-%H.%M.%S.%f"))
    return df


def plot_ipu_usage(directory: Path):
    directory = Path(directory)
    monitoring_files = [*directory.rglob("*.jsonl")]
    fig, ax = plt.subplots(1, 1)
    for file in monitoring_files:
        df = process_monitoring_file(file)
        ax = df.plot(y="ipus_in_use", ax=ax, label=file.parent.name)

    ax.set_ylabel("Number of IPUs in use")
    leg = ax.legend()
    leg.set_bbox_to_anchor((1, -0.25))
    fig.savefig(directory / "ipu_usage.png", dpi=300, bbox_extra_artists=(leg,), bbox_inches="tight")
    return ax.figure
