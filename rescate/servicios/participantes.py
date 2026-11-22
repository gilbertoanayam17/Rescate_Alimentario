"""Alta, edición, baja y sesión de participantes (CAR-09). Una de las tres partes de SRP.

Inicio de sesión con PIN: el rol ya no se elige en la interfaz, sale del participante con el
que se entra. El PIN se guarda como `pbkdf2$iteraciones$sal$hash` (PBKDF2-SHA256 con sal
aleatoria); nunca en claro, ni en la bitácora ni en los registros. Tras 5 intentos fallidos en
5 minutos, ese participante (o el coordinador) queda bloqueado 1 minuto.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timedelta

from rescate.dominio.enums import Rol
from rescate.dominio.modelos import Actor, Participante, ahora
from rescate.persistencia.repositorios import RepositorioDonativos, RepositorioParticipantes

from .autorizacion import es_coordinador, exigir_rol
from .errores import ErrorAutorizacion, ErrorServicio

ITERACIONES = 100_000
INTENTOS_MAXIMOS = 5
VENTANA_INTENTOS = timedelta(minutes=5)
BLOQUEO = timedelta(minutes=1)
CLAVE_COORDINADOR = "__coordinador__"
PIN_INCORRECTO = "PIN incorrecto."


def hashear_pin(pin: str, sal: bytes | None = None, iteraciones: int = ITERACIONES) -> str:
    """'pbkdf2$100000$<sal hex>$<hash hex>'."""
    sal = sal or secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), sal, iteraciones)
    return f"pbkdf2${iteraciones}${sal.hex()}${derivado.hex()}"


def verificar_pin(pin: str, guardado: str) -> bool:
    """Compara en tiempo constante; un hash mal formado nunca valida."""
    try:
        esquema, iteraciones, sal, esperado = guardado.split("$")
        if esquema != "pbkdf2":
            return False
        calculado = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(sal), int(iteraciones))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculado.hex(), esperado)


def validar_formato_pin(pin: str) -> str:
    pin = (pin or "").strip()
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        raise ErrorServicio("El PIN debe tener de 4 a 8 dígitos.")
    return pin


class ServicioParticipantes:
    def __init__(
        self,
        participantes: RepositorioParticipantes,
        donativos: RepositorioDonativos,
        pin_coordinador: str = "0000",
        pin_demo: str | None = None,
        reloj: Callable[[], datetime] = ahora,
    ) -> None:
        self._participantes = participantes
        self._donativos = donativos
        self._pin_coordinador = pin_coordinador  # de Configuracion (PIN_COORDINADOR en .env)
        if pin_demo is None:
            from rescate.config import cargar_configuracion

            pin_demo = cargar_configuracion().pin_demo
        self._pin_demo = pin_demo  # primer inicio de los participantes de la semilla sin PIN
        self._reloj = reloj
        self._fallos: dict[str, deque[datetime]] = defaultdict(deque)
        self._bloqueados: dict[str, datetime] = {}
        self._candado = threading.Lock()

    # ---------------------------------------------------------------- lectura

    def listar(self, rol: Rol | None = None) -> list[Participante]:
        """Lectura libre: la usa la pantalla de entrada para elegir participante."""
        return self._participantes.listar(rol)

    def obtener(self, participante_id: str | None) -> Participante | None:
        return self._participantes.obtener(participante_id) if participante_id else None

    # --------------------------------------------------------------- escritura

    def registrar(self, actor: Actor | None, participante: Participante, pin: str | None = None) -> Participante:
        """Alta o edición (mismo id = edición). El coordinador puede todo y fija el PIN del
        participante con `pin`; un participante solo edita su propio perfil, sin cambiar de rol ni
        de PIN. Sin `pin`, una edición conserva el PIN guardado."""
        if not participante.nombre.strip():
            raise ErrorServicio("El nombre es obligatorio.")
        guardado = self._participantes.obtener(participante.id)
        if not es_coordinador(actor):
            exigir_rol(actor, Rol.DONANTE, Rol.RECEPTOR, Rol.RECOLECTOR)
            if (
                guardado is None
                or actor.participante_id != participante.id
                or guardado.rol != participante.rol
                or actor.rol != guardado.rol
            ):
                raise ErrorAutorizacion("Solo puedes editar tu propio perfil.")
            pin_hash = guardado.pin_hash
        elif pin:
            pin_hash = hashear_pin(validar_formato_pin(pin))
        else:
            pin_hash = participante.pin_hash or (guardado.pin_hash if guardado else "")
        participante = participante.model_copy(update={"pin_hash": pin_hash})
        self._participantes.guardar(participante)
        return participante

    def vinculado(self, participante_id: str) -> bool:
        """True si aparece en algún donativo; se conserva para no romper el historial."""
        return any(
            participante_id in (d.donante_id, d.receptor_id, d.recolector_id)
            or participante_id in d.receptores_descartados
            or (d.asignacion is not None and participante_id in d.asignacion.alternativas)
            for d in self._donativos.listar()
        )

    def eliminar(self, actor: Actor | None, participante_id: str) -> None:
        exigir_rol(actor, Rol.COORDINADOR)
        if self.vinculado(participante_id):
            raise ErrorServicio("Conservamos participantes vinculados a donativos para mantener el historial.")
        self._participantes.eliminar(participante_id)

    def asignar_pin_faltante(self, pin: str) -> int:
        """Da `pin` a los participantes que no tienen (lo usa scripts/cargar_semilla.py)."""
        pin = validar_formato_pin(pin)
        sin_pin = [p for p in self._participantes.listar() if not p.pin_hash]
        for p in sin_pin:
            self._participantes.guardar(p.model_copy(update={"pin_hash": hashear_pin(pin)}))
        return len(sin_pin)

    # ------------------------------------------------------------------ sesión

    def iniciar_sesion(self, participante_id: str, pin: str) -> Actor:
        """El Actor del participante si el PIN es correcto. El rol sale de la base."""
        self._exigir_no_bloqueado(participante_id)
        participante = self._participantes.obtener(participante_id)
        if participante is None:
            self._fallo(participante_id)
            raise ErrorAutorizacion("No existe ese participante.")
        pin = (pin or "").strip()
        if participante.pin_hash:
            valido = verificar_pin(pin, participante.pin_hash)
        else:  # participante de la semilla que nunca entró: su PIN es el de la demo
            valido = bool(pin) and hmac.compare_digest(pin, self._pin_demo)
            if valido:
                self._participantes.guardar(participante.model_copy(update={"pin_hash": hashear_pin(pin)}))
        if not valido:
            self._fallo(participante_id)
            raise ErrorAutorizacion(PIN_INCORRECTO)
        self._fallos.pop(participante_id, None)
        return Actor(rol=participante.rol, participante_id=participante.id)

    def sesion_coordinador(self, pin: str) -> Actor:
        """Sesión del coordinador: su PIN se compara con PIN_COORDINADOR de la configuración."""
        self._exigir_no_bloqueado(CLAVE_COORDINADOR)
        if not hmac.compare_digest((pin or "").strip(), self._pin_coordinador):
            self._fallo(CLAVE_COORDINADOR)
            raise ErrorAutorizacion(PIN_INCORRECTO)
        self._fallos.pop(CLAVE_COORDINADOR, None)
        return Actor(rol=Rol.COORDINADOR)

    # ---------------------------------------------------------------- bloqueo

    def _exigir_no_bloqueado(self, clave: str) -> None:
        with self._candado:
            hasta = self._bloqueados.get(clave)
            if hasta is not None and self._reloj() < hasta:
                raise ErrorAutorizacion("Demasiados intentos fallidos. Espera un minuto e inténtalo de nuevo.")
            self._bloqueados.pop(clave, None)

    def _fallo(self, clave: str) -> None:
        with self._candado:
            momento = self._reloj()
            fallos = self._fallos[clave]
            fallos.append(momento)
            while fallos and momento - fallos[0] > VENTANA_INTENTOS:
                fallos.popleft()
            if len(fallos) >= INTENTOS_MAXIMOS:
                self._bloqueados[clave] = momento + BLOQUEO
                fallos.clear()
