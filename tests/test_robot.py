"""El lote con una sesión falsa: retomar desde el CSV y recuperarse de caídas del navegador."""
import pytest

from siac_scraper import robot as modulo_robot
from siac_scraper.config import Config
from siac_scraper.resultados import FALLO, OK, Resultado
from siac_scraper.robot import Robot


class SesionFalsa:
    abiertas = 0

    def __init__(self, cfg, progreso):
        self.viva = True
        SesionFalsa.abiertas += 1

    def abrir(self):
        pass

    def vivo(self):
        return self.viva

    def reabrir_siac(self):
        pass

    def descartar(self):
        self.viva = False

    def cerrar(self):
        pass


@pytest.fixture
def robot(tmp_path, monkeypatch):
    SesionFalsa.abiertas = 0
    monkeypatch.setattr(modulo_robot, "SesionSiac", SesionFalsa)
    monkeypatch.setattr(modulo_robot.time, "sleep", lambda s: None)
    cfg = Config()
    cfg.lote.resultados = tmp_path / "r.csv"
    return Robot(cfg)


def _consulta(monkeypatch, comportamiento):
    """comportamiento(sesion, ruc) -> Resultado, o lanza."""
    vistos = []

    def consultar(sesion, ruc):
        vistos.append(ruc)
        return comportamiento(sesion, ruc)
    monkeypatch.setattr(modulo_robot, "consultar_ruc", consultar)
    return vistos


def _estados(robot):
    return [(r, x.estado) for r, x in robot.resultados.ultimo_por_ruc().items()]


def test_lote_completo(robot, monkeypatch):
    _consulta(monkeypatch, lambda s, ruc: Resultado(ruc, OK, "", {"cliente": f"C{ruc}"}))
    robot.ejecutar(["1", "2", "3"])
    assert _estados(robot) == [("1", OK), ("2", OK), ("3", OK)]
    assert robot.contadores[OK] == 3


def test_retoma_desde_el_ultimo_ruc_del_csv(robot, monkeypatch):
    robot.resultados.agregar(Resultado("1", OK))
    vistos = _consulta(monkeypatch, lambda s, ruc: Resultado(ruc, OK))
    robot.ejecutar(["1", "2", "3"])
    assert vistos == ["2", "3"]


def test_nada_pendiente_no_abre_el_navegador(robot, monkeypatch):
    robot.resultados.agregar(Resultado("2", OK))
    _consulta(monkeypatch, lambda s, ruc: Resultado(ruc, OK))
    robot.ejecutar(["1", "2"])
    assert SesionFalsa.abiertas == 0


def test_error_con_navegador_vivo_se_guarda_como_fallo_y_sigue(robot, monkeypatch):
    def comportamiento(s, ruc):
        if ruc == "2":
            raise RuntimeError("no encontré la lupa")
        return Resultado(ruc, OK)
    _consulta(monkeypatch, comportamiento)
    robot.ejecutar(["1", "2", "3"])
    assert _estados(robot) == [("1", OK), ("2", FALLO), ("3", OK)]


def test_caida_del_navegador_reabre_y_reintenta_el_mismo_ruc(robot, monkeypatch):
    caidas = {"2": 1}

    def comportamiento(s, ruc):
        if caidas.get(ruc):
            caidas[ruc] -= 1
            s.viva = False
            raise RuntimeError("chrome not reachable")
        return Resultado(ruc, OK)
    vistos = _consulta(monkeypatch, comportamiento)
    robot.ejecutar(["1", "2", "3"])
    assert vistos == ["1", "2", "2", "3"]
    assert _estados(robot) == [("1", OK), ("2", OK), ("3", OK)]
    assert SesionFalsa.abiertas == 2


def test_ruc_que_tumba_el_navegador_se_guarda_como_fallo(robot, monkeypatch):
    def comportamiento(s, ruc):
        if ruc == "2":
            s.viva = False
            raise RuntimeError("chrome not reachable")
        return Resultado(ruc, OK)
    vistos = _consulta(monkeypatch, comportamiento)
    robot.ejecutar(["1", "2", "3"])
    assert vistos == ["1", "2", "2", "3"]              # max_caidas_por_ruc = 2
    assert _estados(robot) == [("1", OK), ("2", FALLO), ("3", OK)]


def test_se_rinde_si_no_avanza(robot, monkeypatch):
    def abrir_que_falla(self):
        self.viva = False
        raise RuntimeError("no abre")
    monkeypatch.setattr(SesionFalsa, "abrir", abrir_que_falla)
    _consulta(monkeypatch, lambda s, ruc: Resultado(ruc, OK))
    with pytest.raises(RuntimeError, match="no abre"):
        robot.ejecutar(["1"])
    assert SesionFalsa.abiertas == 3                    # max_reinicios_sin_avance = 3


def test_error_al_abrir_con_navegador_vivo_no_reintenta(robot, monkeypatch):
    def abrir_que_falla(self):
        raise RuntimeError("No encontré la opción 'SIAC Unico' en el portal")
    monkeypatch.setattr(SesionFalsa, "abrir", abrir_que_falla)
    with pytest.raises(RuntimeError, match="SIAC Unico"):
        robot.ejecutar(["1"])
    assert SesionFalsa.abiertas == 1


def test_resumen_caida(robot, monkeypatch):
    _consulta(monkeypatch, lambda s, ruc: Resultado(ruc, OK))
    robot.ejecutar(["1"])
    titulo, destacados, filas, nota = robot.resumen_caida(RuntimeError("x"), inicio=0)
    assert destacados[0] == ("1", "RUCs extraídos")
    assert ("Último RUC guardado", "1") in filas
    assert nota == "Motivo: RuntimeError: x"
