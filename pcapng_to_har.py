#!/usr/bin/env python3
import json
import logging
import platform
from pathlib import Path
from argparse import ArgumentParser
from typing import Any

from pcapng_utils.har.pirogue_enrichment.decryption import ContentDecryption
from pcapng_utils.har.pirogue_enrichment.stacktrace import Stacktrace
from pcapng_utils.tshark.traffic import NetworkTrafficDump
from pcapng_utils.tshark.wrapper import Tshark

DEFAULT_TSHARK_PATH = {
    "Linux": "/usr/bin/tshark",
    "Darwin": "/Applications/Wireshark.app/Contents/MacOS/tshark",
}.get(platform.system())


def cli() -> None:
    """CLI script for converting .pcapng file to .har file using tshark"""
    parser = ArgumentParser("Convert PCAPng -> HAR")
    parser.add_argument("-i", metavar="PATH", type=str, required=True, help="Path to input .pcapng")
    parser.add_argument("-o", metavar="PATH", type=str, default=None, help="Path to output .har")
    parser.add_argument("-f", "--force", action="store_true", help="Whether to overwrite output if it exists")

    if DEFAULT_TSHARK_PATH and Path(DEFAULT_TSHARK_PATH).exists():
        parser.add_argument(
            "--tshark",
            type=str,
            default=DEFAULT_TSHARK_PATH,
            help=f"Path to tshark executable (default: {DEFAULT_TSHARK_PATH})",
        )
    else:
        parser.add_argument(
            "--tshark",
            type=str,
            required=True,
            help="Path to tshark executable",
        )

    # Arguments for enriching the HAR data
    parser.add_argument(
        "-sf",
        "--socket-operations-file",
        metavar="PATH",
        required=False,
        default=None,
        type=str,
        help="Path to the socket operations data file generated by Pirogue (e.g. socket_trace.json)")
    parser.add_argument(
        "-cf",
        "--cryptography-operations-file",
        metavar="PATH",
        required=False,
        default=None,
        type=str,
        help="Path to the cryptography data file generated by Pirogue (e.g. aes_info.json)")

    args = parser.parse_args()
    try:
        pcapng_to_har(
            args.i,
            args.o,
            tshark=Tshark(args.tshark),
            overwrite=args.force,
            socket_operations_file=args.socket_operations_file,
            cryptographic_operations_file=args.cryptography_operations_file
        )
    except Exception as e:
        raise RuntimeError(args.i) from e


def pcapng_to_har(
    input_file: Path | str,
    output_file: Path | str | None = None,
    *,
    tshark: Tshark | None = None,
    socket_operations_file: Path | str | None = None,
    cryptography_operations_file: Path | str | None = None,
    overwrite: bool = False,
    **json_dump_kws: Any,
) -> None:
    """Convert .pcapng file to .har file using tshark"""
    logger = logging.getLogger("pcapng_to_har")
    input_file = Path(input_file)
    if output_file is None:
        output_file = input_file.with_suffix(".har")
    else:
        output_file = Path(output_file)

    assert output_file != input_file, input_file
    if output_file.exists() and not overwrite:  # fail fast
        raise FileExistsError(output_file)

    if tshark is None:
        tshark = Tshark()  # default executable path

    # Load & parse the traffic from the PCAPNG file
    traffic = NetworkTrafficDump(tshark.load_traffic(input_file))
    traffic.parse_traffic()

    # Save the HAR file
    traffic.save_har(output_file, overwrite=overwrite, **json_dump_kws)

    # Get the HAR data
    har_data = traffic.to_har()

    # Add stacktrace information to the HAR
    enriched = False  # whether the HAR data has been enriched
    socket_operations_file = Path(socket_operations_file) if socket_operations_file else None
    if socket_operations_file and socket_operations_file.is_file():
        enriched = True
        se = Stacktrace(har_data, socket_operations_file)
        se.enrich()
        logger.info(f"The HAR has been enriched with stacktrace data from {socket_operations_file}")
    else:
        logger.error(f"Invalid stacktrace data input file, skip enrichment")

    # Add content decryption to the HAR
    cryptography_operations_file = Path(cryptography_operations_file) if cryptography_operations_file else None
    if cryptography_operations_file and cryptography_operations_file.is_file():
        enriched = True
        de = ContentDecryption(har_data, cryptography_operations_file)
        de.enrich()
        logger.info(f"The HAR has been enriched with decrypted content from {cryptography_operations_file}")
    else:
        logger.error(f"Invalid decryption data input file, skip enrichment")

    # Save the enriched HAR data
    if enriched:
        with output_file.open("w") as f:
            json.dump(har_data, f, **json_dump_kws)

    logger.info(f"The HAR has been saved in {output_file}")


if __name__ == "__main__":
    cli()
