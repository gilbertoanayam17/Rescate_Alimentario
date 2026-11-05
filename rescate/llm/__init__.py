"""Acceso al LLM local detrás de una abstracción (ClienteLLM)."""
from .cliente import ClienteLLM, ErrorLLM

__all__ = ["ClienteLLM", "ErrorLLM"]
