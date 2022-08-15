# Copyright (c) 2022 Graphcore Ltd. All rights reserved.
import argparse
import csv
import logging
import subprocess
import sys
import yaml
from pathlib import Path

HEADER_METRICS = ["benchmark name", "variant_name", "throughput", "latency", "total_compiling_time"]

if __name__ == "__main__":
    # Setup logger
    logger = logging.getLogger()
    formatter = logging.Formatter("[%(levelname)s] %(asctime)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel("INFO")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--spec",
        required=True,
        type=str,
        help="Path to yaml file with benchmark spec",
    )
    parser.add_argument(
        "--sdk-path",
        required=True,
        type=str,
        help="Path to the SDK root dir used for benchmarking",
    )
    args = parser.parse_args()

    benchmarks = yaml.load(open(args.spec).read(), Loader=yaml.FullLoader)
    logger.info("Benchmarks found:")
    for name, _ in benchmarks.items():
        logger.info(f"\t{name}")

    # Write all results into a common CSV
    common_csv_path = Path("./assessment_results.csv").resolve()
    logger.info(f"Saving all results into {str(common_csv_path)}")
    with open(common_csv_path, "w") as common_file:
        # Use a fixed set of headers
        common_writer = csv.writer(common_file, quoting=csv.QUOTE_ALL)
        common_writer.writerow(HEADER_METRICS)

        # Run all benchmarks
        for name, setup in benchmarks.items():
            logger.info(f"Running {name}:")

            if setup.get("additional_dir") is None:
                setup["additional_dir"] = ""
            if setup.get("build_steps") is None:
                setup["build_steps"] = ""

            # Formulate command for each benchmark
            benchmark_cmd = [
                "bash",
                "./assess_platform.sh",
                args.sdk_path,
                setup["application_name"],
                setup["benchmark"],
                setup["additional_dir"],
                setup["build_steps"],
            ]
            logger.info(f"\tcmd = {benchmark_cmd}")

            # Run benchmark in a poplar SDK enabled environment
            log_file = f"./{name}.log"
            with open(log_file, "w") as output_stream:
                logger.info(f"\tlogs at: {log_file}")
                subprocess.run(
                    benchmark_cmd,
                    stdout=output_stream,
                    stderr=output_stream,
                )

            # Merge CSV outputs from this benchmark into the common CSV
            with open(Path(f"/tmp/{setup['application_name']}_logs/benchmark_results.csv"), "r") as benchmark_csv:
                # Skip header
                benchmark_reader = csv.reader(benchmark_csv)
                _ = next(benchmark_reader)

                # Include all results rows
                for row in benchmark_reader:
                    logger.info(f"\tResults = {row} - saved")
                    common_writer.writerow(row)
