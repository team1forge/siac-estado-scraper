import pytest


@pytest.fixture(scope="session")
def chrome():
    """Chrome headless para probar los selectores contra HTML local. Se salta si no hay Chrome."""
    try:
        from selenium import webdriver
        opts = webdriver.ChromeOptions()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        driver = webdriver.Chrome(options=opts)
    except Exception as e:  # pragma: no cover - depende de la máquina
        pytest.skip(f"Chrome no disponible: {e}")
    yield driver
    driver.quit()


@pytest.fixture
def pagina(chrome, tmp_path):
    """Carga un HTML en Chrome: pagina('<table>...</table>')."""
    def cargar(cuerpo, titulo="prueba"):
        archivo = tmp_path / "pagina.html"
        archivo.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>{titulo}</title></head>"
                           f"<body>{cuerpo}</body></html>", encoding="utf-8")
        chrome.get(archivo.as_uri())
        return chrome
    return cargar
