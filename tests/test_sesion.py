"""Inicio de sesión con PIN y su configuración."""
from __future__ import annotations

from rescate.config import cargar_configuracion


def test_los_pin_salen_de_la_configuracion(monkeypatch):
    monkeypatch.setenv("PIN_DEMO", " 4321 ")
    monkeypatch.setenv("PIN_COORDINADOR", "9999")
    config = cargar_configuracion()
    assert (config.pin_demo, config.pin_coordinador) == ("4321", "9999")


def test_pin_por_defecto(monkeypatch):
    monkeypatch.delenv("PIN_DEMO", raising=False)
    monkeypatch.delenv("PIN_COORDINADOR", raising=False)
    config = cargar_configuracion()
    assert (config.pin_demo, config.pin_coordinador) == ("1234", "0000")
