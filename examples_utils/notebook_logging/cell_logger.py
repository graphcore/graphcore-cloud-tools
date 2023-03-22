# Copyright (c) 2023 Graphcore Ltd. All rights reserved.

import json

from datetime import datetime
from pathlib import Path


class CellLogger(object):
    """Tracks the times at which cells are executed"""

    def __init__(self, ip):
        self.shell = ip

        self.log_path = Path("/root/.ipython/extensions/cell_logs/").resolve()
        self.log_path.mkdir(parents=True, exist_ok=True)

    def __write_to_file(self, content, filepath):
        """Write text or dict to a txt or json file"""

        # Write to ipython cache to be sure
        try:
            cache_path = self.log_path.joinpath(filepath)

            with open(cache_path, "w") as outfile:
                if "txt" in filepath:
                    outfile.write(content)

                elif "json" in filepath:
                    json.dump(content, outfile)

                else:
                    return

        # Silently skip if not possible
        except:
            pass

    def pre_run_cell(self, info):
        """Runs just before any cell is run"""

        # TODO: Can we get cell ID? Perhaps output too?
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        code = info.raw_cell

        self.__write_to_file(code, f"{timestamp}.txt")

    def post_run_cell(self, result):
        """Runs just after any cell is run"""

        # Only do anything if error
        if result.error_before_exec or result.error_in_exec:
            timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            error_dict = {
                "code": result.info.raw_cell,
                "error": str(result.error_before_exec) if result.error_before_exec else str(result.error_in_exec),
            }

            self.__write_to_file(error_dict, f"errors/{timestamp}.json")


def load_ipython_extension(ip):
    tracker = CellLogger(ip)
    ip.events.register("pre_run_cell", tracker.pre_run_cell)
    ip.events.register("post_run_cell", tracker.post_run_cell)
