"""Sensor sources. Every source yields the same Reading shape, so the rest of
the system cannot tell synthetic data from a real I2C bus."""
from .base import Reading, SensorSource  # noqa: F401
