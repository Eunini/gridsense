import os
from dataclasses import dataclass, field

DEMO_DEVICE = "inverter-01"
# Deliberately public simulator credential. Real deployments require provisioning.
DEMO_TOKEN = "gridsense-public-demo-inverter"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///data/runtime/gridsense.db")
    )
    demo_mode: bool = field(
        default_factory=lambda: os.getenv("DEMO_MODE", "true").lower() == "true"
    )
    operator_token: str = field(default_factory=lambda: os.getenv("OPERATOR_TOKEN", ""))

    def validate(self):
        if not self.demo_mode and len(self.operator_token) < 32:
            raise ValueError(
                "Set a random OPERATOR_TOKEN of at least 32 characters outside demo mode."
            )
