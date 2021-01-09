"""Provision one site and its primary inverter without printing credentials."""

import argparse
import os

from .config import DEMO_TOKEN, Settings
from .storage import Device, Site, digest, setup_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--device", required=True)
    args = parser.parse_args()
    token = os.getenv("DEVICE_TOKEN", "")
    if len(token) < 32 or token == DEMO_TOKEN:
        parser.error("Set a unique DEVICE_TOKEN of at least 32 characters in the environment")
    engine, sessions = setup_database(Settings().database_url)
    with sessions() as session:
        if session.get(Device, args.device):
            parser.error("Device already exists; provision a unique device ID")
        site = Site(name=args.name, location=args.location, battery_capacity_kwh=10.24)
        session.add(site)
        session.flush()
        session.add(Device(id=args.device, site_id=site.id, token_hash=digest(token)))
        session.commit()
        print(f"Provisioned site {site.id} and device {args.device}; credential stored as a hash.")
    engine.dispose()


if __name__ == "__main__":
    main()
