"""Excel de entrada, CSV de resultados, métricas y divisor."""
import csv

import pytest
from openpyxl import Workbook

from siac_scraper.divisor import dividir
from siac_scraper.entrada import leer_rucs
from siac_scraper.metricas import calcular, reporte
from siac_scraper.resultados import (BLOQUEO, COLUMNAS, FALLO, OK, SIN_DATOS, ArchivoResultados,
                                     Resultado)


def _excel(ruta, filas, hoja="Hoja1"):
    wb = Workbook()
    ws = wb.active
    ws.title = hoja
    for fila in filas:
        ws.append(fila)
    wb.save(ruta)
    return ruta


def _leer_csv(ruta):
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


# ------------------------------ Excel ------------------------------
def test_leer_rucs_detecta_columna_y_limpia(tmp_path):
    ruta = _excel(tmp_path / "e.xlsx", [["Nombre", "RUC"], ["A", 20123456789], ["B", "20999999999 "],
                                        ["C", 20123456789], ["D", None]])
    assert leer_rucs(ruta) == ["20123456789", "20999999999"]


def test_leer_rucs_sin_encabezados(tmp_path):
    ruta = _excel(tmp_path / "e.xlsx", [[20123456789], [20999999999], [20123456789]])
    assert leer_rucs(ruta) == ["20123456789", "20999999999"]


def test_leer_rucs_columna_por_nombre_e_indice(tmp_path):
    ruta = _excel(tmp_path / "e.xlsx", [["id", "doc"], [1, "111"], [2, "222"]])
    assert leer_rucs(ruta, columna="doc") == ["111", "222"]
    assert leer_rucs(ruta, columna=0) == ["1", "2"]


def test_leer_rucs_sin_extension(tmp_path):
    _excel(tmp_path / "80k.xlsx", [["RUC"], ["20123456789"]])
    assert leer_rucs(tmp_path / "80k") == ["20123456789"]


def test_leer_rucs_no_existe(tmp_path):
    with pytest.raises(FileNotFoundError):
        leer_rucs(tmp_path / "nada.xlsx")


# ------------------------------- CSV -------------------------------
def test_agregar_y_retomar(tmp_path):
    archivo = ArchivoResultados(tmp_path / "datos" / "r.csv")
    assert archivo.ultimo_ruc() is None
    archivo.agregar(Resultado("1", OK, "", {"cliente": "ACME SAC", "email": "a@b.pe"}))
    archivo.agregar(Resultado("2", BLOQUEO, "No está autorizado"))
    filas = _leer_csv(archivo.ruta)
    assert filas[0] == COLUMNAS
    assert filas[1] == ["1", "VALIDO", "ACME SAC", "", "", "", "a@b.pe", "OK", ""]
    assert filas[2][:2] == ["2", "BLOQUEADO"]
    assert archivo.ultimo_ruc() == "2"
    assert archivo.cantidad_rucs() == 2
    assert archivo.ruta.read_bytes().count(b"\xef\xbb\xbf") == 1     # un solo BOM al agregar


def test_preparar_migra_formato_anterior(tmp_path):
    ruta = tmp_path / "r.csv"
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["ruc", "cliente", "contacto", "representante_legal", "telefono", "email"])
        w.writerows([["1", "ACME", "", "", "", ""], ["2", "ERROR", "", "", "", ""], ["3", "", "", "", "", ""]])
    archivo = ArchivoResultados(ruta)
    archivo.preparar()
    filas = _leer_csv(ruta)
    assert filas[0] == COLUMNAS
    assert [(f[0], f[1], f[7]) for f in filas[1:]] == [("1", "VALIDO", OK), ("2", "VACIO", FALLO),
                                                       ("3", "VACIO", SIN_DATOS)]
    assert archivo.ultimo_ruc() == "3"


def test_preparar_aparta_csv_ajeno(tmp_path):
    ruta = tmp_path / "r.csv"
    ruta.write_text("otra,cosa\n1,2\n", encoding="utf-8")
    ArchivoResultados(ruta).preparar()
    assert not ruta.exists()
    assert len(list(tmp_path.glob("r_anterior_*.csv"))) == 1


# ----------------------------- métricas -----------------------------
def test_metricas_usa_la_ultima_fila_de_cada_ruc(tmp_path):
    archivo = ArchivoResultados(tmp_path / "r.csv")
    archivo.agregar(Resultado("1", FALLO, "excepción"))
    archivo.agregar(Resultado("1", OK, "", {"cliente": "ACME"}))
    archivo.agregar(Resultado("2", SIN_DATOS, "popup sin productos"))
    archivo.agregar(Resultado("3", BLOQUEO, "No está autorizado"))
    m = calcular(archivo)
    assert (m.total, m.filas) == (3, 4)
    assert (m.cantidad(OK), m.vacios, m.cantidad(BLOQUEO)) == (1, 1, 1)
    assert m.incompletos["email"] == 1
    texto = "\n".join(reporte(m, "r.csv"))
    assert "popup sin productos" in texto and "RUCs: 3" in texto


# ------------------------------ divisor ------------------------------
def test_dividir(tmp_path):
    archivo = ArchivoResultados(tmp_path / "r.csv")
    archivo.agregar(Resultado("1", OK, "", {"cliente": "ACME"}))
    archivo.agregar(Resultado("2", SIN_DATOS))
    archivo.agregar(Resultado("3", BLOQUEO))
    assert dividir(archivo.ruta) == (1, 2)
    assert [f[0] for f in _leer_csv(tmp_path / "rucs_validos.csv")[1:]] == ["1"]
    assert [f[0] for f in _leer_csv(tmp_path / "rucs_vacios.csv")[1:]] == ["2", "3"]
