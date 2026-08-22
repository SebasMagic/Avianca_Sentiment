# Plan A — Extracción del framework multi-cliente

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separar la calibración de mercado, sector y cliente del motor de brand monitoring, de modo que Avianca siga produciendo un dashboard idéntico al de hoy y un cliente nuevo (Burger King Bolivia) se declare solo con archivos de configuración.

**Architecture:** Cuatro capas — motor (`config.py`, scrapers, pipeline, dashboard), mercado (`markets/`), sector (`sectors/`) y cliente (`clients/<slug>/`). Ningún módulo del motor importa calibración: la recibe como parámetro, extendiendo la convención que ya se usa con `brand`. Se aplica patrón estrangulador: primero se crea la capa nueva y `config.py` reexporta desde ella (nada se rompe), después se desacopla cada consumidor, y al final se borran las reexportaciones.

**Tech Stack:** Python 3.12 · SQLite (`sqlite3` stdlib) · pytest · `importlib` para cargar perfiles. **Sin dependencias nuevas.**

**Spec:** `docs/superpowers/specs/2026-08-22-framework-multicliente-design.md`

## Global Constraints

- **Python 3.12.** No agregar dependencias a `requirements.txt`.
- **Plan A no gasta un centavo de API.** Ninguna tarea llama a DataForSEO, Apify ni DeepSeek. Cualquier test que necesite esas respuestas usa fixtures.
- **Windows:** anteponer `PYTHONIOENCODING=utf-8` a todo comando que imprima texto con tildes o eñes (prácticamente todos los de este proyecto). La consola cp1252 revienta el proceso si no.
- **Suite base: 389 tests en verde, ~25s** (`python -m pytest`). Ninguna tarea puede cerrarse con menos de 389 pasando, salvo donde el plan diga explícitamente cuántos se agregan.
- **Criterio de regresión (spec §10):** el dashboard de Avianca regenerado debe ser idéntico a `dashboard/avianca_dashboard_2026-08-22.html` salvo la fecha de generación. Se verifica en la Tarea 11.
- **`--client` es obligatorio** en todo comando que toque datos, a partir de la Tarea 10. No se conserva compatibilidad hacia atrás.
- **Nombres exactos de los tres diccionarios de perfil:** `MARKET`, `SECTOR`, `CLIENT` (mayúsculas, a nivel de módulo).
- **Fuera de alcance en Plan A:** el marcador `__DRIVER_LABELS__` del dashboard, el scraper de Google Business, la columna `branch` y toda captura real. Eso es Plan B (fases 5-7 del spec).

---

## Estructura de archivos

**Se crean:**

| Archivo | Responsabilidad |
|---|---|
| `markets/__init__.py` | Paquete vacío |
| `markets/colombia.py` | `MARKET` de Colombia (`location_code` 2170, medios colombianos) |
| `markets/bolivia.py` | `MARKET` de Bolivia (`location_code` 2068) |
| `sectors/__init__.py` | Paquete vacío |
| `sectors/aerolineas.py` | `SECTOR` de aerolíneas — toda la calibración que hoy vive en `config.py` |
| `sectors/restaurantes.py` | `SECTOR` de restaurantes — drivers semilla |
| `clients/__init__.py` | Paquete vacío |
| `clients/avianca/__init__.py`, `client.py` | `CLIENT` de Avianca (marcas Avianca + LATAM) |
| `clients/burger-king-bo/__init__.py`, `client.py` | `CLIENT` de Burger King Bolivia |
| `tests/test_context.py` | Tests del cargador y sus validaciones |
| `tests/test_profiles_contract.py` | Contrato de todo perfil del repo |
| `tests/test_client_isolation.py` | Dos clientes en el mismo proceso |
| `tests/test_migration_regression.py` | Criterio de regresión del spec §10 |

**Se modifican:** `config.py`, `pipeline/relevance.py`, `pipeline/classifier.py`, `pipeline/classify_pending.py`, `pipeline/ai_visibility.py`, `scrapers/dataforseo_*.py` (6 archivos), `store/db.py`, `dashboard/aggregate.py`, `dashboard/ai_visibility_aggregate.py`, `dashboard/build.py`, `main.py`, `tests/conftest.py`, `.gitignore`.

**Nota sobre `clients/burger-king-bo/`:** el guion en el nombre impide `import clients.burger-king-bo.client`. Por eso el cargador usa `importlib.import_module` con la ruta construida como string y un `__init__.py` en cada carpeta; nunca un `import` literal. La Tarea 1 lo cubre con un test.

---

## Tarea 1: Cargador de perfiles y `RunContext`

**Files:**
- Modify: `config.py` (agregar al final, sin tocar nada existente)
- Create: `markets/__init__.py`, `sectors/__init__.py`, `clients/__init__.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `config.RunContext` — `@dataclass(frozen=True)` con atributos `client: dict`, `market: dict`, `sector: dict`; métodos `brands() -> dict[str, dict]`, `brand(name: str) -> dict`, `competitors_of(name: str) -> list[str]`; propiedades `db_path -> str`, `deploy_dir -> str`, `own_brand -> str`.
  - `config.load_client(slug: str) -> RunContext`
  - `config.available_clients() -> list[str]`
  - `config.ProfileError` — subclase de `ValueError`.

- [ ] **Step 0: Congelar la referencia de regresión ANTES de tocar una sola línea**

El criterio del spec §10 exige comparar contra el dashboard **anterior a todo el refactor**. Ese archivo existe en disco pero **no está versionado** (`.gitignore` tiene `dashboard/avianca_dashboard_*.html`), así que se perdería. Congelarlo ahora, con el código todavía intacto:

```bash
mkdir -p tests/fixtures
cp dashboard/avianca_dashboard_2026-08-22.html tests/fixtures/avianca_dashboard_referencia.html
printf '\n# Referencia de regresion del spec §10 — SI se versiona\n!tests/fixtures/avianca_dashboard_referencia.html\n' >> .gitignore
git add -f tests/fixtures/avianca_dashboard_referencia.html .gitignore
git commit -m "test: congela el dashboard de Avianca como referencia de regresion"
```

Expected: el archivo queda versionado. Verificar con `git show --stat HEAD | head`.

**Si este paso se salta, la Tarea 11 no puede verificar nada**: la referencia generada después del refactor solo probaría que mover archivos no rompe, que es la parte fácil.

- [ ] **Step 1: Crear los tres paquetes vacíos**

```bash
mkdir -p markets sectors clients
touch markets/__init__.py sectors/__init__.py clients/__init__.py
```

- [ ] **Step 2: Escribir el test que falla**

Crear `tests/test_context.py`:

```python
import pytest

import config


def _market(**over):
    base = {
        "slug": "testland", "name": "Testland", "country_code": "TL",
        "language_code": "es", "location_code": 9999,
        "cities": ["Ciudad Uno"], "recognized_media_domains": {"diariotest"},
    }
    base.update(over)
    return base


def _sector(**over):
    base = {
        "slug": "testsector", "name": "Test Sector",
        "complaint_drivers": ["demora", "otro"],
        "driver_precedence": ["demora", "otro"],
        "driver_labels": {"demora": "Demoras", "otro": "Otro"},
        "context_words": {"cosa"}, "context_phrases": set(),
        "context_substring_terms": set(), "blacklist_domain_roots": set(),
        "review_source": "trustpilot",
        "ai_category_prompt_templates": ["¿mejor en {city}?"],
        "ai_brand_prompt_templates": ["¿Es confiable {brand}?"],
        "share_of_voice_problem_terms": ["queja"],
        "share_of_voice_commercial_terms": ["ofertas"],
        "classifier_role": "la empresa {keyword} en {market_name}",
        "has_loyalty_program": False,
    }
    base.update(over)
    return base


def _client(**over):
    base = {
        "slug": "testclient", "name": "Test Client",
        "market": "testland", "sector": "testsector",
        "own_brand": "Propia", "competitors": [],
        "brands": {"Propia": {"keyword": "Propia", "color": "#123456"}},
        "db_path": "data/testclient.db", "deploy_dir": "deploy",
        "report_window_start": "2026-01-01", "backfill_since": "2026-04-19",
    }
    base.update(over)
    return base


def _ctx(**over):
    parts = {"client": _client(), "market": _market(), "sector": _sector()}
    parts.update(over)
    return config.RunContext(**parts)


def test_brand_devuelve_el_perfil():
    assert _ctx().brand("Propia")["keyword"] == "Propia"


def test_brand_desconocida_falla_con_mensaje_claro():
    with pytest.raises(config.ProfileError) as exc:
        _ctx().brand("Fantasma")
    assert "Fantasma" in str(exc.value)
    assert "Propia" in str(exc.value)


def test_competitors_of_se_deriva_de_las_marcas_del_cliente():
    ctx = _ctx(client=_client(
        competitors=["Rival"],
        brands={"Propia": {"keyword": "Propia", "color": "#123456"},
                "Rival": {"keyword": "Rival", "color": "#654321"}},
    ))
    assert ctx.competitors_of("Propia") == ["Rival"]
    assert ctx.competitors_of("Rival") == ["Propia"]


def test_db_path_se_resuelve_bajo_la_carpeta_del_cliente():
    assert _ctx().db_path.replace("\\", "/").endswith(
        "clients/testclient/data/testclient.db")


def test_run_context_es_inmutable():
    with pytest.raises(Exception):
        _ctx().client = {}


def test_validate_rechaza_own_brand_ausente_de_brands():
    with pytest.raises(config.ProfileError, match="own_brand"):
        config.validate_context(_ctx(client=_client(own_brand="NoExiste")))


def test_validate_rechaza_marca_que_no_es_propia_ni_competidora():
    ctx = _ctx(client=_client(
        competitors=[],
        brands={"Propia": {"keyword": "Propia", "color": "#123456"},
                "Huerfana": {"keyword": "Huerfana", "color": "#000000"}},
    ))
    with pytest.raises(config.ProfileError, match="Huerfana"):
        config.validate_context(ctx)


def test_validate_rechaza_precedence_que_no_es_permutacion():
    with pytest.raises(config.ProfileError, match="driver_precedence"):
        config.validate_context(_ctx(sector=_sector(driver_precedence=["demora"])))


def test_validate_exige_otro_en_drivers():
    with pytest.raises(config.ProfileError, match="otro"):
        config.validate_context(_ctx(sector=_sector(
            complaint_drivers=["demora"], driver_precedence=["demora"],
            driver_labels={"demora": "Demoras"})))


def test_validate_exige_color_en_cada_marca():
    with pytest.raises(config.ProfileError, match="color"):
        config.validate_context(_ctx(client=_client(
            brands={"Propia": {"keyword": "Propia"}})))


def test_validate_exige_loyalty_program_si_el_sector_lo_declara():
    with pytest.raises(config.ProfileError, match="loyalty_program"):
        config.validate_context(_ctx(sector=_sector(has_loyalty_program=True)))


def test_validate_exige_review_target_str_en_trustpilot():
    ctx = _ctx(client=_client(brands={
        "Propia": {"keyword": "Propia", "color": "#123456",
                   "review_target": [{"branch": "X", "cid": "1"}]}}))
    with pytest.raises(config.ProfileError, match="review_target"):
        config.validate_context(ctx)


def test_validate_exige_review_target_lista_en_google_business():
    ctx = _ctx(
        sector=_sector(review_source="google_business"),
        client=_client(brands={
            "Propia": {"keyword": "Propia", "color": "#123456",
                       "review_target": "ejemplo.com"}}),
    )
    with pytest.raises(config.ProfileError, match="review_target"):
        config.validate_context(ctx)


def test_review_target_ausente_es_valido():
    config.validate_context(_ctx())  # no lanza


def test_load_client_desconocido_falla_con_mensaje_claro():
    with pytest.raises(config.ProfileError) as exc:
        config.load_client("no-existe")
    assert "no-existe" in str(exc.value)
```

- [ ] **Step 3: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_context.py -q`
Expected: FAIL con `AttributeError: module 'config' has no attribute 'RunContext'`

- [ ] **Step 4: Implementar el cargador**

Agregar al final de `config.py`:

```python
# ── Capas de calibración: mercado / sector / cliente ─────────────────────
#
# El motor no conoce ningún perfil: los recibe como parámetro. Esta sección
# solo sabe CARGAR y VALIDAR perfiles, nunca su contenido.
import importlib
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent


class ProfileError(ValueError):
    """
    Perfil mal declarado o inexistente. Subclase de ValueError para no
    romper a quien ya capture ValueError (get_brand lanzaba ValueError).

    Todo fallo de perfil se detecta al CARGAR, nunca a mitad de una corrida
    que ya gastó API — ese es el punto de validate_context().
    """


@dataclass(frozen=True)
class RunContext:
    """
    Calibración completa de una corrida. Inmutable a propósito: ningún
    módulo del motor debe poder mutarla a mitad de camino.
    """
    client: dict
    market: dict
    sector: dict

    def brands(self) -> dict:
        return self.client["brands"]

    def brand(self, name: str) -> dict:
        try:
            return self.client["brands"][name]
        except KeyError:
            raise ProfileError(
                f"Marca desconocida para el cliente {self.client['slug']!r}: "
                f"{name!r}. Marcas disponibles: {', '.join(self.client['brands'])}"
            ) from None

    def competitors_of(self, name: str) -> list[str]:
        """
        Competidores de `name` = las demás marcas del cliente. Derivado, no
        declarado: antes cada marca listaba a la otra a mano y había que
        mantener la simetría sincronizada.
        """
        return [b for b in self.client["brands"] if b != name]

    @property
    def own_brand(self) -> str:
        return self.client["own_brand"]

    @property
    def client_dir(self) -> Path:
        return _REPO_ROOT / "clients" / self.client["slug"]

    @property
    def db_path(self) -> str:
        return str(self.client_dir / self.client["db_path"])

    @property
    def deploy_dir(self) -> str:
        return str(self.client_dir / self.client["deploy_dir"])


def _load_profile(module_path: str, attr: str, what: str) -> dict:
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise ProfileError(f"No existe el {what} {module_path!r}: {exc}") from None
    try:
        return getattr(module, attr)
    except AttributeError:
        raise ProfileError(
            f"{module_path!r} no define {attr!r} — todo {what} debe declarar "
            f"un diccionario {attr} a nivel de módulo."
        ) from None


def available_clients() -> list[str]:
    """Slugs de clients/ que tienen un client.py. Ordenados, para que la
    ayuda de la CLI y los mensajes de error sean estables."""
    root = _REPO_ROOT / "clients"
    if not root.is_dir():
        return []
    return sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and (d / "client.py").is_file()
    )


def validate_context(ctx: RunContext) -> None:
    """
    Todas las invariantes de un perfil, verificadas de una sola vez y con
    mensajes que nombran el archivo culpable. Ver spec §4.
    """
    client, sector = ctx.client, ctx.sector
    where = f"clients/{client['slug']}/client.py"

    brands = client["brands"]
    own = client["own_brand"]
    if own not in brands:
        raise ProfileError(
            f"{where}: own_brand={own!r} no está en brands "
            f"({', '.join(brands) or 'vacío'})")

    declared = set(client["competitors"])
    derived = set(brands) - {own}
    if declared != derived:
        faltan = derived - declared
        sobran = declared - derived
        detalle = []
        if faltan:
            detalle.append(f"en brands pero no en competitors: {', '.join(sorted(faltan))}")
        if sobran:
            detalle.append(f"en competitors pero no en brands: {', '.join(sorted(sobran))}")
        raise ProfileError(f"{where}: competitors no cuadra con brands — {'; '.join(detalle)}")

    for name, profile in brands.items():
        if not profile.get("color"):
            raise ProfileError(
                f"{where}: la marca {name!r} no declara 'color'. Es requerido: "
                "dashboard/build.py deriva tres variables CSS por contraste y no "
                "tiene default sensato.")
        if sector["has_loyalty_program"] and not profile.get("loyalty_program"):
            raise ProfileError(
                f"{where}: la marca {name!r} no declara 'loyalty_program', pero el "
                f"sector {sector['slug']!r} tiene has_loyalty_program=True.")
        _validate_review_target(profile.get("review_target"), name, sector, where)

    drivers = sector["complaint_drivers"]
    sector_where = f"sectors/{sector['slug']}.py"
    if "otro" not in drivers:
        raise ProfileError(
            f"{sector_where}: complaint_drivers debe incluir 'otro' — es el "
            "destino obligado de toda queja que no encaje en ninguna categoría.")
    if sorted(sector["driver_precedence"]) != sorted(drivers):
        raise ProfileError(
            f"{sector_where}: driver_precedence no es una permutación de "
            f"complaint_drivers ({len(sector['driver_precedence'])} vs {len(drivers)} "
            "elementos, o nombres distintos).")
    faltan_labels = set(drivers) - set(sector["driver_labels"])
    if faltan_labels:
        raise ProfileError(
            f"{sector_where}: driver_labels no cubre {', '.join(sorted(faltan_labels))}")


def _validate_review_target(target, brand_name: str, sector: dict, where: str) -> None:
    """La forma de review_target la manda el review_source del sector: un
    dominio (str) en Trustpilot, una lista de sucursales en Google Business.
    Ausente es válido — significa 'este cliente no compró reseñas'."""
    if target is None:
        return
    source = sector["review_source"]
    if source == "trustpilot" and not isinstance(target, str):
        raise ProfileError(
            f"{where}: {brand_name!r} tiene review_target de tipo "
            f"{type(target).__name__}, pero review_source='trustpilot' espera un "
            "dominio (str).")
    if source == "google_business":
        if not isinstance(target, list) or not all(
            isinstance(t, dict) and "branch" in t for t in target
        ):
            raise ProfileError(
                f"{where}: {brand_name!r} tiene review_target inválido para "
                "review_source='google_business' — se espera una lista de dicts "
                "con al menos la clave 'branch'.")


def load_client(slug: str) -> RunContext:
    """
    Contexto completo de un cliente: su perfil, su mercado y su sector, ya
    validados. Falla acá y con mensaje claro, nunca con un KeyError críptico
    dentro de un scraper a mitad de corrida.
    """
    if slug not in available_clients():
        raise ProfileError(
            f"Cliente desconocido: {slug!r}. Clientes disponibles: "
            f"{', '.join(available_clients()) or 'ninguno'}")
    client = _load_profile(f"clients.{slug}.client", "CLIENT", "cliente")
    market = _load_profile(f"markets.{client['market']}", "MARKET", "mercado")
    sector = _load_profile(f"sectors.{client['sector']}", "SECTOR", "sector")
    ctx = RunContext(client=client, market=market, sector=sector)
    validate_context(ctx)
    return ctx
```

- [ ] **Step 5: Correr los tests hasta verde**

Run: `python -m pytest tests/test_context.py -q`
Expected: PASS (17 tests)

- [ ] **Step 6: Verificar que no se rompió nada**

Run: `python -m pytest -q`
Expected: 406 passed (389 previos + 17 nuevos)

- [ ] **Step 7: Commit**

```bash
git add config.py markets/__init__.py sectors/__init__.py clients/__init__.py tests/test_context.py
git commit -m "feat: cargador de perfiles y RunContext (mercado/sector/cliente)"
```

---

## Tarea 2: `sectors/aerolineas.py`

Mueve la calibración aeronáutica fuera de `config.py`. `config.py` reexporta desde el sector para que ningún consumidor se entere todavía — patrón estrangulador: la capa nueva es la fuente de verdad desde ya, los consumidores migran en las tareas 5-9, y las reexportaciones se borran en la Tarea 10.

**Files:**
- Create: `sectors/aerolineas.py`
- Modify: `config.py`
- Test: `tests/test_profiles_contract.py`

**Interfaces:**
- Consumes: `config.RunContext`, `config.validate_context` (Tarea 1).
- Produces: `sectors.aerolineas.SECTOR` — dict con las 16 claves de spec §4.

- [ ] **Step 1: Escribir el test de contrato que falla**

Crear `tests/test_profiles_contract.py`:

```python
"""
Contrato de forma de TODO perfil del repo. Un sectors/*.py mal escrito debe
fallar acá, en 25 segundos de suite, no en una corrida que ya gastó API.
"""
import importlib

import pytest

import config

SECTOR_KEYS = {
    "slug", "name", "complaint_drivers", "driver_precedence", "driver_labels",
    "context_words", "context_phrases", "context_substring_terms",
    "blacklist_domain_roots", "review_source", "ai_category_prompt_templates",
    "ai_brand_prompt_templates", "share_of_voice_problem_terms",
    "share_of_voice_commercial_terms", "classifier_role", "has_loyalty_program",
}
MARKET_KEYS = {
    "slug", "name", "country_code", "language_code", "location_code",
    "cities", "recognized_media_domains",
}


def _sector_slugs():
    root = config._REPO_ROOT / "sectors"
    return sorted(p.stem for p in root.glob("*.py") if p.stem != "__init__")


@pytest.mark.parametrize("slug", _sector_slugs())
def test_sector_declara_todas_las_claves(slug):
    sector = importlib.import_module(f"sectors.{slug}").SECTOR
    assert set(sector) == SECTOR_KEYS, (
        f"sectors/{slug}.py: faltan {SECTOR_KEYS - set(sector)}, "
        f"sobran {set(sector) - SECTOR_KEYS}")
    assert sector["slug"] == slug
    assert sector["review_source"] in {"trustpilot", "google_business"}
    assert isinstance(sector["has_loyalty_program"], bool)


@pytest.mark.parametrize("slug", _sector_slugs())
def test_sector_vocabulario_sin_tildes_y_en_minuscula(slug):
    """relevance.py compara contra texto ya normalizado (NFKD, minúscula).
    Un término con tilde o mayúscula en el sector nunca haría match."""
    import unicodedata
    sector = importlib.import_module(f"sectors.{slug}").SECTOR
    for key in ("context_words", "context_phrases", "context_substring_terms"):
        for term in sector[key]:
            assert term == term.lower(), f"{slug}.{key}: {term!r} tiene mayúsculas"
            sin_tilde = "".join(
                c for c in unicodedata.normalize("NFKD", term)
                if not unicodedata.combining(c))
            assert term == sin_tilde, f"{slug}.{key}: {term!r} tiene tildes"


def test_aerolineas_conserva_los_doce_drivers():
    """Los drivers de Avianca salieron de leer 368 quejas reales. Si esta
    lista cambia, el dashboard histórico deja de ser comparable."""
    from sectors.aerolineas import SECTOR
    assert SECTOR["complaint_drivers"] == [
        "equipaje", "cancelacion", "demora", "atencion_cliente",
        "cobros_tarifas", "programa_fidelidad", "asientos_comida",
        "reembolsos", "mascotas", "fraude_publicidad", "rechazo_marca", "otro",
    ]
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `python -m pytest tests/test_profiles_contract.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sectors.aerolineas'`

- [ ] **Step 3: Crear `sectors/aerolineas.py`**

Mover desde `config.py` a `sectors/aerolineas.py`, **conservando íntegros los comentarios de calibración** (documentan verificaciones contra datos reales que costaron dinero y no se pueden re-derivar):

| Símbolo en `config.py` | Clave en `SECTOR` |
|---|---|
| `COMPLAINT_DRIVERS` | `complaint_drivers` |
| `AVIATION_CONTEXT_WORDS` | `context_words` |
| `AVIATION_CONTEXT_PHRASES` | `context_phrases` |
| `AVIATION_CONTEXT_SUBSTRING_TERMS` | `context_substring_terms` |
| `BLACKLIST_DOMAIN_ROOTS` | `blacklist_domain_roots` |
| `AI_VISIBILITY_CATEGORY_PROMPTS` | `ai_category_prompt_templates` |
| `AI_VISIBILITY_BRAND_PROMPT_TEMPLATES` | `ai_brand_prompt_templates` |
| `SHARE_OF_VOICE_PROBLEM_TERMS` | `share_of_voice_problem_terms` |
| `SHARE_OF_VOICE_COMMERCIAL_TERMS` | `share_of_voice_commercial_terms` |

Claves que **no** existían y se crean con estos valores exactos:

```python
# Orden de desempate cuando una queja encaja en varios drivers. Sale del
# texto de build_system_prompt() en pipeline/classifier.py, donde vivía
# como prosa dentro del prompt — acá es dato, y el cargador valida que sea
# una permutación de complaint_drivers.
"driver_precedence": [
    "cancelacion", "demora", "equipaje", "mascotas", "reembolsos",
    "cobros_tarifas", "fraude_publicidad", "programa_fidelidad",
    "asientos_comida", "atencion_cliente", "rechazo_marca", "otro",
],

# Etiquetas legibles. Copiadas VERBATIM de dashboard/template.html:875 —
# cualquier diferencia cambia el dashboard de Avianca y rompe el criterio
# de regresión del spec §10. En Plan A nadie las consume todavía (el
# template sigue con su literal JS); el marcador __DRIVER_LABELS__ es
# Plan B, fase 6.
"driver_labels": {
    "equipaje": "Equipaje", "cancelacion": "Cancelaciones",
    "demora": "Demoras", "atencion_cliente": "Atención al cliente",
    "cobros_tarifas": "Cobros y tarifas",
    "programa_fidelidad": "Programa de fidelidad",
    "asientos_comida": "Asientos y comida", "reembolsos": "Reembolsos",
    "mascotas": "Mascotas", "fraude_publicidad": "Fraude y publicidad",
    "rechazo_marca": "Rechazo a la marca", "otro": "Otro",
},

"slug": "aerolineas",
"name": "Aerolíneas",
"review_source": "trustpilot",
"classifier_role": "la aerolínea {keyword} en {market_name}",
"has_loyalty_program": True,
```

**Antes de escribir `driver_labels`**, leer `dashboard/template.html:875` y copiar los valores literalmente. Si alguno difiere de lo de arriba, gana el template y hay que corregir el plan.

- [ ] **Step 4: Reexportar desde `config.py`**

Reemplazar en `config.py` los bloques movidos por:

```python
# Reexportado desde sectors/aerolineas.py mientras dura la migración
# (Tareas 2-9). La fuente de verdad ya es el sector; estas líneas existen
# solo para que los consumidores sigan funcionando hasta que cada uno reciba
# el sector por parámetro. Se BORRAN en la Tarea 10.
from sectors.aerolineas import SECTOR as _AEROLINEAS

COMPLAINT_DRIVERS = _AEROLINEAS["complaint_drivers"]
AVIATION_CONTEXT_WORDS = _AEROLINEAS["context_words"]
AVIATION_CONTEXT_PHRASES = _AEROLINEAS["context_phrases"]
AVIATION_CONTEXT_SUBSTRING_TERMS = _AEROLINEAS["context_substring_terms"]
BLACKLIST_DOMAIN_ROOTS = _AEROLINEAS["blacklist_domain_roots"]
AI_VISIBILITY_CATEGORY_PROMPTS = _AEROLINEAS["ai_category_prompt_templates"]
AI_VISIBILITY_BRAND_PROMPT_TEMPLATES = _AEROLINEAS["ai_brand_prompt_templates"]
SHARE_OF_VOICE_PROBLEM_TERMS = _AEROLINEAS["share_of_voice_problem_terms"]
SHARE_OF_VOICE_COMMERCIAL_TERMS = _AEROLINEAS["share_of_voice_commercial_terms"]
```

- [ ] **Step 5: Correr toda la suite**

Run: `python -m pytest -q`
Expected: 410 passed (406 + 4 nuevos de contrato). **Ningún test previo puede fallar** — si alguno falla, un valor se transcribió mal al mover.

- [ ] **Step 6: Commit**

```bash
git add sectors/aerolineas.py config.py tests/test_profiles_contract.py
git commit -m "refactor: extrae la calibracion aeronautica a sectors/aerolineas.py"
```

---

## Tarea 3: `markets/colombia.py`

**Files:**
- Create: `markets/colombia.py`
- Modify: `config.py`, `tests/test_profiles_contract.py`

**Interfaces:**
- Consumes: Tarea 1.
- Produces: `markets.colombia.MARKET` con las 7 claves de spec §4.

- [ ] **Step 1: Agregar el test de contrato de mercados**

Agregar a `tests/test_profiles_contract.py`:

```python
def _market_slugs():
    root = config._REPO_ROOT / "markets"
    return sorted(p.stem for p in root.glob("*.py") if p.stem != "__init__")


@pytest.mark.parametrize("slug", _market_slugs())
def test_market_declara_todas_las_claves(slug):
    market = importlib.import_module(f"markets.{slug}").MARKET
    assert set(market) == MARKET_KEYS, (
        f"markets/{slug}.py: faltan {MARKET_KEYS - set(market)}, "
        f"sobran {set(market) - MARKET_KEYS}")
    assert market["slug"] == slug
    assert isinstance(market["location_code"], int)
    assert len(market["country_code"]) == 2
    assert market["cities"], "cities no puede estar vacío: rellena {city} en los prompts"


def test_colombia_conserva_el_location_code_de_produccion():
    from markets.colombia import MARKET
    assert MARKET["location_code"] == 2170
    assert MARKET["language_code"] == "es"
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `python -m pytest tests/test_profiles_contract.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'markets.colombia'`

- [ ] **Step 3: Crear `markets/colombia.py`**

```python
"""
Mercado Colombia. Lo que cambia por PAÍS, no por sector ni por cliente.

RECOGNIZED_MEDIA_DOMAINS vive acá y no en el sector porque El Tiempo es
prensa tanto para una aerolínea como para un restaurante.
"""

MARKET = {
    "slug": "colombia",
    "name": "Colombia",
    "country_code": "CO",
    "language_code": "es",
    # Verificado contra la API real de DataForSEO. Disponible en serp,
    # business_data y keywords_data.
    "location_code": 2170,
    "cities": ["Bogotá", "Medellín", "Cali"],
    # Movido de config.RECOGNIZED_MEDIA_DOMAINS — conservar íntegro el
    # comentario de calibración original, que documenta por qué la lista no
    # es "cualquier medio nacional grande".
    "recognized_media_domains": {
        "eltiempo", "caracol", "elespectador", "semana", "portafolio",
        "elcolombiano", "infobae", "elheraldo", "publimetro",
        "asuntoslegales", "bluradio", "reportur",
    },
}
```

Al mover `RECOGNIZED_MEDIA_DOMAINS`, **copiar el comentario completo de ~30 líneas** que hoy lo precede en `config.py`: documenta la verificación con datos reales del 2026-08-21/22 y la razón de que forbes.co esté excluido.

- [ ] **Step 4: Reexportar desde `config.py`**

Reemplazar el bloque de `RECOGNIZED_MEDIA_DOMAINS` y las tres variables de entorno geográficas:

```python
# Reexportado desde markets/colombia.py — se BORRA en la Tarea 10.
from markets.colombia import MARKET as _COLOMBIA

RECOGNIZED_MEDIA_DOMAINS = _COLOMBIA["recognized_media_domains"]
COUNTRY_CODE = _COLOMBIA["country_code"]
LANGUAGE_CODE = _COLOMBIA["language_code"]
LOCATION_CODE = _COLOMBIA["location_code"]
```

Borrar los `os.getenv("COUNTRY_CODE"...)`, `os.getenv("LANGUAGE_CODE"...)` y `os.getenv("LOCATION_CODE"...)`: el mercado manda, no el entorno.

- [ ] **Step 5: Correr toda la suite**

Run: `python -m pytest -q`
Expected: 413 passed (410 + 3 nuevos). Ninguno previo falla.

- [ ] **Step 6: Commit**

```bash
git add markets/colombia.py config.py tests/test_profiles_contract.py
git commit -m "refactor: extrae la calibracion geografica a markets/colombia.py"
```

---

## Tarea 4: `clients/avianca/client.py`

**Files:**
- Create: `clients/avianca/__init__.py`, `clients/avianca/client.py`
- Modify: `config.py`, `tests/test_profiles_contract.py`

**Interfaces:**
- Consumes: Tareas 1-3.
- Produces: `clients.avianca.client.CLIENT`; `config.load_client("avianca")` funcional.

- [ ] **Step 1: Agregar el test de contrato de clientes**

Agregar a `tests/test_profiles_contract.py`:

```python
CLIENT_KEYS = {
    "slug", "name", "market", "sector", "own_brand", "competitors", "brands",
    "db_path", "deploy_dir", "report_window_start", "backfill_since",
}


@pytest.mark.parametrize("slug", config.available_clients())
def test_cliente_carga_y_valida(slug):
    """Cargar cada cliente del repo con todas las validaciones puestas."""
    ctx = config.load_client(slug)
    assert set(ctx.client) == CLIENT_KEYS, (
        f"clients/{slug}/client.py: faltan {CLIENT_KEYS - set(ctx.client)}, "
        f"sobran {set(ctx.client) - CLIENT_KEYS}")
    assert ctx.client["slug"] == slug


def test_avianca_conserva_sus_dos_marcas():
    ctx = config.load_client("avianca")
    assert ctx.own_brand == "Avianca"
    assert set(ctx.brands()) == {"Avianca", "LATAM"}
    assert ctx.competitors_of("Avianca") == ["LATAM"]
    assert ctx.sector["slug"] == "aerolineas"
    assert ctx.market["slug"] == "colombia"


def test_avianca_conserva_el_dominio_de_trustpilot():
    ctx = config.load_client("avianca")
    assert ctx.brand("Avianca")["review_target"] == "avianca.com"
    assert ctx.brand("LATAM")["review_target"] == "latamairlines.com"
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `python -m pytest tests/test_profiles_contract.py -q`
Expected: FAIL — `test_avianca_conserva_sus_dos_marcas` con `ProfileError: Cliente desconocido: 'avianca'`

- [ ] **Step 3: Crear `clients/avianca/client.py`**

Mover `config.BRANDS` completo, **con todos sus comentarios de verificación** (documentan handles comprobados contra Apify el 2026-08-20 y conteos reales de Trustpilot del 2026-08-21). Dos cambios de forma:

1. Renombrar `review_domain` → `review_target` en ambas marcas.
2. **Borrar** la clave `competitors` de cada marca — ahora se deriva con `ctx.competitors_of()`.

```python
"""
Cliente Avianca — aerolíneas, Colombia. Marca propia Avianca, competidor
LATAM monitoreado para ella (por eso comparten esta base y este dashboard).
"""

CLIENT = {
    "slug": "avianca",
    "name": "Avianca",
    "market": "colombia",
    "sector": "aerolineas",
    "own_brand": "Avianca",
    "competitors": ["LATAM"],
    "db_path": "data/avianca.db",
    "deploy_dir": "deploy",
    # Movidos de config.REPORT_WINDOW_START / config.BACKFILL_SINCE.
    "report_window_start": "2026-01-01",
    "backfill_since": "2026-04-19",
    "brands": {
        # Copiar el diccionario BRANDS["Avianca"] y BRANDS["LATAM"] tal como
        # están hoy en config.py, ÍNTEGROS y con todos sus comentarios de
        # verificación, aplicando solo los dos cambios de forma de abajo.
        "Avianca": {...},
        "LATAM": {...},
    },
}
```

Los dos cambios de forma, marca por marca:

| Hoy en `config.BRANDS` | En `clients/avianca/client.py` |
|---|---|
| `"review_domain": "avianca.com"` | `"review_target": "avianca.com"` |
| `"review_domain": "latamairlines.com"` | `"review_target": "latamairlines.com"` |
| `"competitors": ["LATAM"]` | **borrar** (lo deriva `ctx.competitors_of`) |
| `"competitors": ["Avianca"]` | **borrar** |

Todo lo demás — `name`, `keyword`, `instagram_profiles`, `domains`, `tiktok_hashtags`, `tiktok_official_accounts`, `loyalty_program`, `color`, `logo` — se copia sin tocar. Los comentarios largos que acompañan a `tiktok_official_accounts`, `review_domain` y `tiktok_hashtags` documentan verificaciones contra la API real de Apify y Trustpilot: **perderlos cuesta dinero re-derivarlos**.

- [ ] **Step 4: Reexportar desde `config.py`**

```python
# Reexportado desde clients/avianca/client.py — se BORRA en la Tarea 10.
from clients.avianca.client import CLIENT as _AVIANCA

BRANDS = _AVIANCA["brands"]
DEFAULT_BRAND = _AVIANCA["own_brand"]
REPORT_WINDOW_START = _AVIANCA["report_window_start"]
BACKFILL_SINCE = _AVIANCA["backfill_since"]
```

`get_brand()`, `get_ai_prompts()` y `get_share_of_voice_keywords()` se quedan intactas de momento: siguen leyendo `BRANDS`, que ahora apunta al cliente. Se borran en la Tarea 10.

**Ojo:** `get_ai_prompts()` lee `brand["competitors"]`, clave que este paso elimina. Cambiar esa línea a:

```python
    competitors = [b for b in BRANDS if b != brand_name]
```

- [ ] **Step 5: Correr toda la suite**

Run: `python -m pytest -q`
Expected: 416 passed (413 + 3). Ninguno previo falla. Si `test_dataforseo_ai_visibility.py` o `test_dataforseo_ai_prompts.py` fallan, es por `review_domain` → `review_target`: actualizar esos tests y los scrapers que lean la clave vieja.

- [ ] **Step 6: Commit**

```bash
git add clients/ config.py tests/test_profiles_contract.py
git commit -m "refactor: extrae el perfil de Avianca a clients/avianca/client.py"
```

---

## Tarea 5: Desacoplar `pipeline/relevance.py`

**Files:**
- Modify: `pipeline/relevance.py`, `main.py`, `pipeline/social_relevance_backfill.py`
- Test: `tests/test_relevance.py`

**Interfaces:**
- Consumes: `sectors.aerolineas.SECTOR` (Tarea 2).
- Produces:
  - `is_relevant(mention: dict, brand: dict, sector: dict, recognized_media_domains: set | None = None) -> tuple[bool, str]`
  - `is_spanish(text: str) -> bool` (sin cambios)

  El cuarto parámetro existe porque los medios reconocidos son del **mercado**, no del sector (El Tiempo es prensa para cualquier rubro). Se pasa como valor y no como el dict de mercado completo para que `relevance.py` siga siendo una función pura sin conocimiento de la forma de un perfil.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_relevance.py`:

```python
def test_is_relevant_usa_el_vocabulario_del_sector_que_recibe():
    """El sector llega por parámetro, no por import. Con un sector cuyo
    vocabulario no incluye términos aeronáuticos, un video de TikTok que
    hoy pasa debe dejar de pasar."""
    from pipeline.relevance import is_relevant
    from sectors.aerolineas import SECTOR as AEROLINEAS

    mention = {"platform": "tiktok", "author": "randomuser",
               "text": "mi vuelo con avianca se retrasó 5 horas"}
    brand = {"keyword": "Avianca", "domains": set(), "tiktok_official_accounts": set()}

    ok, _ = is_relevant(mention, brand, AEROLINEAS)
    assert ok is True

    sector_sin_vocabulario = dict(AEROLINEAS, context_words=set(),
                                  context_phrases=set(), context_substring_terms=set())
    ok, razon = is_relevant(mention, brand, sector_sin_vocabulario)
    assert ok is False
    assert razon == "sin_contexto_aeronautico"


def test_blacklist_sale_del_sector_no_de_config():
    from pipeline.relevance import is_relevant
    from sectors.aerolineas import SECTOR as AEROLINEAS

    mention = {"platform": "web", "author": "www.kayak.com",
               "text": "vuelos baratos con Avianca " + "palabra " * 20}
    brand = {"keyword": "Avianca", "domains": set()}

    assert is_relevant(mention, brand, AEROLINEAS) == (False, "agregador")
    sector_sin_blacklist = dict(AEROLINEAS, blacklist_domain_roots=set())
    ok, _ = is_relevant(mention, brand, sector_sin_blacklist)
    assert ok is True
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `python -m pytest tests/test_relevance.py -q`
Expected: FAIL — `TypeError: is_relevant() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Implementar**

En `pipeline/relevance.py`:

1. Borrar del `from config import (...)` estos cinco: `AVIATION_CONTEXT_PHRASES`, `AVIATION_CONTEXT_SUBSTRING_TERMS`, `AVIATION_CONTEXT_WORDS`, `BLACKLIST_DOMAIN_ROOTS`, `RECOGNIZED_MEDIA_DOMAINS`. Conservar `LANG_MIN_STOPWORDS`, `LANG_MIN_WORDS`, `SPANISH_STOPWORDS` (recursos de idioma, siguen en el motor).
2. Agregar `sector: dict` como tercer parámetro posicional de `is_relevant`, `_is_hashtag_relevant`, `_is_press_relevant`, `_has_aviation_context`, `_is_blacklisted`, `_is_recognized_media_domain`, y pasarlo hacia abajo.
3. Dentro de cada helper, leer del `sector` en vez de la constante global:

```python
def _is_blacklisted(domain: str, sector: dict) -> bool:
    roots = sector["blacklist_domain_roots"]
    return any(label in roots for label in domain.split("."))


def _has_aviation_context(text: str, sector: dict) -> bool:
    words = sector["context_words"]
    substrings = sector["context_substring_terms"]
    phrases = sector["context_phrases"]
    normalized = _strip_accents(text or "").lower()
    normalized = normalized.replace("check-in", "checkin").replace("check in", "checkin")
    tokens = _ASCII_WORD_RE.findall(normalized)
    if set(tokens) & words:
        return True
    if any(term in token for token in tokens for term in substrings):
        return True
    return any(phrase in normalized for phrase in phrases)
```

`_is_recognized_media_domain` necesita el **mercado**, no el sector. Para no cambiar dos firmas a la vez, en esta tarea recibe la lista directamente:

```python
def _is_recognized_media_domain(domain: str, recognized: set) -> bool:
    return any(label in recognized for label in domain.split("."))
```

y `_is_press_relevant` la toma de un cuarto parámetro `recognized_media_domains: set`, que `is_relevant` recibe como parámetro con nombre:

```python
def is_relevant(mention: dict, brand: dict, sector: dict,
                recognized_media_domains: set | None = None) -> tuple[bool, str]:
```

4. Actualizar el docstring del módulo: donde dice que el vocabulario viene de `config`, ahora viene del sector recibido.

- [ ] **Step 4: Actualizar los llamadores**

`main.py:181` — cambiar `is_relevant(m, brand)` por:

```python
        ok, razon = is_relevant(m, brand, ctx.sector,
                                ctx.market["recognized_media_domains"])
```

(en esta tarea `ctx` todavía no existe en `main.py`; usar de momento
`from sectors.aerolineas import SECTOR` y `from markets.colombia import MARKET`,
que la Tarea 10 reemplaza por `ctx`).

`pipeline/social_relevance_backfill.py` — mismo cambio en su llamada.

- [ ] **Step 5: Actualizar los tests existentes de relevancia**

`tests/test_relevance.py` tiene 74 referencias a Avianca/LATAM y llama a `is_relevant` con dos argumentos. Agregar en la cabecera:

```python
from sectors.aerolineas import SECTOR as AEROLINEAS
from markets.colombia import MARKET as COLOMBIA
```

y pasar `AEROLINEAS` como tercer argumento y `COLOMBIA["recognized_media_domains"]` como cuarto en cada llamada.

- [ ] **Step 6: Correr toda la suite**

Run: `python -m pytest -q`
Expected: 418 passed (416 + 2). Ninguno previo falla.

- [ ] **Step 7: Commit**

```bash
git add pipeline/relevance.py main.py pipeline/social_relevance_backfill.py tests/test_relevance.py
git commit -m "refactor: relevance.py recibe el sector por parametro"
```

---

## Tarea 6: Desacoplar `pipeline/classifier.py`

**Files:**
- Modify: `pipeline/classifier.py`, `pipeline/classify_pending.py`
- Test: `tests/test_classifier.py`

**Interfaces:**
- Consumes: Tarea 2.
- Produces:
  - `build_system_prompt(brand: dict, sector: dict, market: dict) -> str`
  - `classify_texts(texts: list[str], brand: dict, sector: dict, market: dict) -> list[dict | None]`
  - `normalize_result(raw: dict, sector: dict) -> dict | None`
  - `classify_pending.run(conn, brand: dict, sector: dict, market: dict) -> dict`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_classifier.py`:

```python
def test_system_prompt_usa_el_rol_del_sector_y_el_nombre_del_mercado():
    from pipeline.classifier import build_system_prompt
    from sectors.aerolineas import SECTOR as AEROLINEAS
    from markets.colombia import MARKET as COLOMBIA

    brand = {"keyword": "Avianca", "loyalty_program": "LifeMiles"}
    prompt = build_system_prompt(brand, AEROLINEAS, COLOMBIA)
    assert "la aerolínea Avianca en Colombia" in prompt
    assert "LifeMiles" in prompt


def test_system_prompt_lista_los_drivers_del_sector():
    from pipeline.classifier import build_system_prompt
    from sectors.aerolineas import SECTOR as AEROLINEAS
    from markets.colombia import MARKET as COLOMBIA

    prompt = build_system_prompt(
        {"keyword": "X", "loyalty_program": "Y"}, AEROLINEAS, COLOMBIA)
    for driver in AEROLINEAS["complaint_drivers"]:
        assert f'"{driver}"' in prompt


def test_system_prompt_omite_fidelidad_cuando_el_sector_no_lo_tiene():
    from pipeline.classifier import build_system_prompt
    from sectors.aerolineas import SECTOR as AEROLINEAS
    from markets.colombia import MARKET as COLOMBIA

    sector = dict(
        AEROLINEAS, has_loyalty_program=False,
        complaint_drivers=[d for d in AEROLINEAS["complaint_drivers"]
                           if d != "programa_fidelidad"],
        driver_precedence=[d for d in AEROLINEAS["driver_precedence"]
                           if d != "programa_fidelidad"],
    )
    prompt = build_system_prompt({"keyword": "X", "loyalty_program": None},
                                 sector, COLOMBIA)
    assert "programa_fidelidad" not in prompt


def test_normalize_result_valida_contra_los_drivers_del_sector():
    from pipeline.classifier import normalize_result
    from sectors.aerolineas import SECTOR as AEROLINEAS

    raw = {"sentiment_positive": 0.0, "sentiment_negative": 1.0,
           "sentiment_neutral": 0.0, "emotion": "anger",
           "is_service_conversation": True, "is_complaint": True,
           "complaint_driver": "pedido_incorrecto"}
    out = normalize_result(raw, AEROLINEAS)
    assert out["complaint_driver"] == "otro", (
        "un driver ajeno al sector cae a 'otro', no se cuela")
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `python -m pytest tests/test_classifier.py -q`
Expected: FAIL — `TypeError: build_system_prompt() takes 1 positional argument but 3 were given`

- [ ] **Step 3: Implementar**

En `pipeline/classifier.py`:

1. Borrar `COMPLAINT_DRIVERS` del import de `config` (queda solo `DEEPSEEK_API_KEY`).
2. **Agregar la clave 17 al sector.** Las glosas largas de cada driver (el texto descriptivo que hoy va inline en el prompt) son calibración de sector, no del motor. En `sectors/aerolineas.py`, declararlas como constante de módulo y sumarlas a `SECTOR`:

```python
# sectors/aerolineas.py
DRIVER_GLOSSES = {
    "equipaje": "maletas perdidas, dañadas o demoradas (manejo físico del equipaje)",
    "cancelacion": "vuelos cancelados, reprogramados sin aviso",
    "demora": "retrasos, conexiones perdidas por retraso",
    "atencion_cliente": "mal trato, call center, falta de respuesta, personal",
    "cobros_tarifas": "cobros indebidos, precios, cargos ocultos, penalidades, cobros de equipaje",
    "programa_fidelidad": "millas, programa de fidelidad ({loyalty_program}), redenciones",
    "asientos_comida": "asientos, espacio, comida a bordo, entretenimiento",
    "reembolsos": "devoluciones de dinero que no llegan o se demoran",
    # Las glosas de mascotas, fraude_publicidad, rechazo_marca y otro son
    # multilínea en el prompt actual — copiarlas VERBATIM desde
    # pipeline/classifier.py:build_system_prompt(). Su texto documenta
    # distinciones calibradas contra 368 quejas reales.
}

SECTOR = {
    ...,
    "driver_glosses": DRIVER_GLOSSES,
}
```

y sumar `"driver_glosses"` a `SECTOR_KEYS` en `tests/test_profiles_contract.py`: el contrato pasa de 16 a 17 claves.

3. Reescribir `build_system_prompt` para construir el bloque de drivers y la precedencia a partir del sector:

```python
def build_system_prompt(brand: dict, sector: dict, market: dict) -> str:
    keyword = brand["keyword"]
    role = sector["classifier_role"].format(
        keyword=keyword, market_name=market["name"])
    loyalty = brand.get("loyalty_program") or ""
    glosses = sector["driver_glosses"]
    drivers_block = "\n".join(
        f'    "{d}" — {glosses[d].format(loyalty_program=loyalty)}'
        for d in sector["complaint_drivers"]
    )
    precedence = " > ".join(sector["driver_precedence"])
    return f"""Eres un analizador de menciones de marca en español latinoamericano, especializado en {role}.
...
"""
```

El resto del prompt (formato JSON, reglas de sentiment, `is_service_conversation`) es motor y no cambia: **copiarlo verbatim**, sustituyendo solo las apariciones de `{keyword}` que ya estaban y el bloque de drivers/precedencia que ahora se genera.

4. Si `sector["has_loyalty_program"]` es falso, `programa_fidelidad` no está en `complaint_drivers` (lo garantiza el perfil), así que el bloque generado simplemente no lo incluye — sin condicionales extra en el clasificador.
5. `normalize_result(raw, sector)` valida `complaint_driver` contra `sector["complaint_drivers"]` en vez de la constante global.
6. Propagar `sector`/`market` por `_call_api`, `_attempt` y `classify_texts`.
7. `pipeline/classify_pending.py:run(conn, brand)` → `run(conn, brand, sector, market)`.

- [ ] **Step 4: Actualizar los tests existentes**

`tests/test_classifier.py` y `tests/test_classify_pending.py`: importar `SECTOR as AEROLINEAS` y `MARKET as COLOMBIA` y pasarlos en cada llamada.

- [ ] **Step 5: Correr toda la suite**

Run: `python -m pytest -q`
Expected: 422 passed (418 + 4). El test de contrato ahora exige 17 claves de sector.

- [ ] **Step 6: Verificar que el prompt no cambió para Avianca**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "from pipeline.classifier import build_system_prompt; from sectors.aerolineas import SECTOR as S; from markets.colombia import MARKET as M; from clients.avianca.client import CLIENT as C; print(build_system_prompt(C['brands']['Avianca'], S, M))" > /tmp/prompt_nuevo.txt
git stash && PYTHONIOENCODING=utf-8 python -c "from pipeline.classifier import build_system_prompt; from config import get_brand; print(build_system_prompt(get_brand('Avianca')))" > /tmp/prompt_viejo.txt; git stash pop
diff /tmp/prompt_viejo.txt /tmp/prompt_nuevo.txt
```
Expected: sin diferencias. Si las hay, una glosa se transcribió mal — el clasificador cambiaría de comportamiento y el histórico dejaría de ser comparable.

- [ ] **Step 7: Commit**

```bash
git add pipeline/classifier.py pipeline/classify_pending.py sectors/aerolineas.py tests/
git commit -m "refactor: classifier.py recibe sector y mercado por parametro"
```

---

## Tarea 7: Desacoplar los scrapers de DataForSEO

**Files:**
- Modify: `scrapers/dataforseo_scraper.py`, `dataforseo_news.py`, `dataforseo_reviews.py`, `dataforseo_ai_prompts.py`, `dataforseo_ai_visibility.py`, `dataforseo_share_of_voice.py`
- Test: los seis `tests/test_dataforseo_*.py`

**Interfaces:**
- Consumes: Tareas 2-3.
- Produces: firma uniforme `scrape(brand: dict, market: dict, sector: dict, since: str | None = None)` en los seis scrapers. `dataforseo_ai_visibility.scrape_comparison(brands: dict, market: dict) -> dict`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_dataforseo_market_param.py`:

```python
"""Un mismo proceso debe poder consultar dos mercados. Antes imposible:
LOCATION_CODE se resolvía una vez al importar."""
from unittest.mock import patch

from markets.bolivia import MARKET as BOLIVIA  # creado en la Tarea 12
from markets.colombia import MARKET as COLOMBIA
from sectors.aerolineas import SECTOR as AEROLINEAS


@patch("scrapers.dataforseo_news.requests.post")
def test_news_usa_el_location_code_del_mercado_recibido(mock_post):
    from scrapers import dataforseo_news
    mock_post.return_value.json.return_value = {"tasks": [{"result": []}]}
    mock_post.return_value.raise_for_status.return_value = None
    brand = {"keyword": "X", "name": "X"}

    dataforseo_news.scrape(brand, COLOMBIA, AEROLINEAS, since="2026-01-01")
    assert mock_post.call_args.kwargs["json"][0]["location_code"] == 2170

    dataforseo_news.scrape(brand, BOLIVIA, AEROLINEAS, since="2026-01-01")
    assert mock_post.call_args.kwargs["json"][0]["location_code"] == 2068
```

**Nota de orden:** este test importa `markets/bolivia.py`, que se crea en la Tarea 12. Si se ejecuta el plan estrictamente en orden, crear `markets/bolivia.py` acá con solo `location_code`/`language_code` y completarlo en la Tarea 12, o mover este test a la Tarea 12. Preferir lo primero.

- [ ] **Step 2: Correr para verificar que falla**

Run: `python -m pytest tests/test_dataforseo_market_param.py -q`
Expected: FAIL — `TypeError` por la firma, o `ModuleNotFoundError: markets.bolivia`

- [ ] **Step 3: Implementar en los seis scrapers**

En cada uno:
1. Borrar `LOCATION_CODE` y `LANGUAGE_CODE` del import de `config`.
2. Agregar `market: dict, sector: dict` a `scrape()` tras `brand`.
3. Reemplazar cada uso de la constante por `market["location_code"]` / `market["language_code"]`.

Específicos:
- `dataforseo_share_of_voice.py`: la función que arma las keywords deja de leer `config.SHARE_OF_VOICE_*` y usa `sector["share_of_voice_problem_terms"]` / `["share_of_voice_commercial_terms"]`. `config.get_share_of_voice_keywords()` se borra en la Tarea 10.
- `dataforseo_ai_prompts.py`: deja de llamar `config.get_ai_prompts()`. Los prompts de categoría se expanden con las ciudades del mercado:

```python
def build_prompts(brand: dict, competitors: list[str],
                  sector: dict, market: dict) -> list[dict]:
    prompts = []
    for template in sector["ai_category_prompt_templates"]:
        if "{city}" in template:
            for city in market["cities"]:
                prompts.append({"prompt": template.format(city=city),
                                "scope": "category"})
        else:
            prompts.append({"prompt": template, "scope": "category"})
    for template in sector["ai_brand_prompt_templates"]:
        if "{competitor}" in template:
            for competitor in competitors:
                prompts.append({"prompt": template.format(
                    brand=brand["keyword"], competitor=competitor,
                    loyalty_program=brand.get("loyalty_program") or ""),
                    "scope": "brand"})
        else:
            prompts.append({"prompt": template.format(
                brand=brand["keyword"], competitor="",
                loyalty_program=brand.get("loyalty_program") or ""),
                "scope": "brand"})
    return prompts
```

- `dataforseo_reviews.py`: lee `brand["review_target"]` (renombrado en la Tarea 4) y verifica `sector["review_source"] == "trustpilot"`; si no lo es, imprime que el sector usa otra fuente y devuelve `[]`. El scraper de Google Business es Plan B.
- `dataforseo_ai_visibility.py`: `scrape_comparison(brand_names=None)` deja de leer `config.BRANDS`; pasa a `scrape_comparison(brands: dict, market: dict)` donde `brands` es `ctx.brands()`.

- [ ] **Step 4: Actualizar los seis archivos de test**

Pasar `COLOMBIA` y `AEROLINEAS` en cada llamada a `scrape()`.

- [ ] **Step 5: Correr toda la suite**

Run: `python -m pytest -q`
Expected: 423 passed (422 + 1). Ninguno previo falla.

- [ ] **Step 6: Commit**

```bash
git add scrapers/ markets/bolivia.py tests/
git commit -m "refactor: los scrapers de DataForSEO reciben mercado y sector"
```

---

## Tarea 8: Desacoplar `store/db.py`

**Files:**
- Modify: `store/db.py`, `store/seed_excel.py`, `pipeline/excel_writer.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: Tarea 1.
- Produces: `db.connect(path: str)` — sin default. `db.fingerprint(...)` sin cambios. `SCHEMA` con el default de `brand` fijado literal.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_db.py`:

```python
def test_connect_exige_ruta_explicita():
    """Sin default no hay forma de escribir en la base de otro cliente por
    accidente."""
    import inspect
    from store import db
    assert inspect.signature(db.connect).parameters["path"].default is inspect.Parameter.empty


def test_db_no_importa_nada_de_config():
    from pathlib import Path
    fuente = Path("store/db.py").read_text(encoding="utf-8")
    assert "from config import" not in fuente
    assert "import config" not in fuente
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `python -m pytest tests/test_db.py -q`
Expected: FAIL en ambos.

- [ ] **Step 3: Implementar**

1. Borrar `from config import DB_PATH, DEFAULT_BRAND`.
2. `_DEFAULT_BRAND_SQL` usaba `DEFAULT_BRAND`. El `DEFAULT` de la columna `brand` es un valor histórico del esquema: fijarlo literal y documentarlo.

```python
# Default histórico de la columna `brand`. NO es "la marca del cliente
# actual": es el valor con el que se rellenaron las filas que existían antes
# de que la columna se agregara (migración de 2026-08-20). Cambiarlo
# reescribiría el sentido de esas filas. Todo INSERT nuevo pasa brand
# explícito, así que este default no se usa en la práctica.
_LEGACY_BRAND_DEFAULT = "Avianca"
```

3. `_add_brand_column_and_refingerprint` usa `DEFAULT_BRAND` para recalcular fingerprints de filas viejas: cambiar a `_LEGACY_BRAND_DEFAULT` (mismo valor, misma semántica, sin depender de config).
4. `connect(path: str)` — quitar el default.
5. `store/seed_excel.py` y `pipeline/excel_writer.py` reciben la marca por parámetro en vez de `DEFAULT_BRAND`.

- [ ] **Step 4: Correr toda la suite**

Run: `python -m pytest -q`
Expected: 425 passed (423 + 2). Los tests que llamaban `db.connect()` sin argumentos ahora pasan una ruta temporal.

- [ ] **Step 5: Commit**

```bash
git add store/ pipeline/excel_writer.py tests/test_db.py
git commit -m "refactor: db.py deja de depender de config (ruta explicita)"
```

---

## Tarea 9: Desacoplar el dashboard

**Files:**
- Modify: `dashboard/aggregate.py`, `dashboard/ai_visibility_aggregate.py`, `dashboard/build.py`, `pipeline/ai_visibility.py`, `pipeline/web_channel_retirement.py`
- Test: `tests/test_aggregate.py`, `tests/test_build.py`

**Interfaces:**
- Consumes: Tareas 1-4.
- Produces:
  - `aggregate.build_payload(conn, ctx, brand: str | None = None) -> dict`
  - `build.render(payload, ctx, template_path=str(TEMPLATE)) -> str`
  - `build.build(ctx, conn=None, out_dir: str | None = None, brand: str | None = None) -> str`
  - `build.stage_for_deploy(html_path: str, ctx, brand: str) -> str`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_build.py`:

```python
def test_render_toma_color_y_nombre_del_contexto(tmp_db):
    import config
    from dashboard import build
    ctx = config.load_client("avianca")
    payload = {"kpis": {"total": 0}}
    html = build.render(payload, ctx)
    assert ctx.brand("Avianca")["color"] in html
    assert "__BRAND_NAME__" not in html


def test_build_respeta_la_ventana_de_reporte_del_cliente(tmp_db):
    """report_window_start deja de ser global: sale del cliente."""
    import config
    from dashboard import aggregate
    ctx = config.load_client("avianca")
    assert ctx.client["report_window_start"] == "2026-01-01"
    payload = aggregate.build_payload(tmp_db, ctx, brand="Avianca")
    assert payload["kpis"]["total"] == 0
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `python -m pytest tests/test_build.py -q`
Expected: FAIL — `TypeError: render() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Implementar**

1. `aggregate.py`: borrar `from config import REPORT_WINDOW_START, WEB_CHANNEL_RETIREMENT_REASON, get_brand`. `WEB_CHANNEL_RETIREMENT_REASON` es constante de motor y se sigue importando; `REPORT_WINDOW_START` sale de `ctx.client["report_window_start"]`; `get_brand` → `ctx.brand`.
2. `_in_report_window(m)` → `_in_report_window(m, window_start)`. Propagar desde `build_payload`.
3. `build.py`: `DEFAULT_BRAND`/`get_brand` → `ctx`. Dos destinos distintos, no confundirlos: `build()` escribe el HTML **de trabajo** y con `out_dir=None` usa `ctx.client_dir / "dashboard"`; `stage_for_deploy()` escribe el **publicado** en `ctx.deploy_dir`.
4. `_deploy_filename(brand)` — sin cambios (usa el slug de marca).
5. `pipeline/ai_visibility.py`: borrar `from config import BRANDS`; `run_comparison(conn)` → `run_comparison(conn, ctx)`.
6. `pipeline/web_channel_retirement.py` — **no cambia**. Importa `WEB_CHANNEL_RETIREMENT_REASON`, que es constante de motor y se queda en `config.py`. Aparece en la lista de archivos de esta tarea solo para confirmar que se revisó y no requiere cambios.

- [ ] **Step 4: Actualizar los tests existentes**

`tests/test_aggregate.py` (61 refs), `test_aggregate_press_reviews.py`, `test_ai_visibility_aggregate.py`, `test_build.py` (52 refs): construir `ctx = config.load_client("avianca")` en un fixture de `conftest.py` y pasarlo.

Agregar a `tests/conftest.py` **los dos fixtures** que pide el spec §11 — uno real para los tests de calibración, uno sintético para los del motor:

```python
@pytest.fixture
def ctx_avianca():
    """Contexto REAL de Avianca. Solo para tests que verifican calibración de
    producción (relevancia aeronáutica, prompt del clasificador, dashboard)."""
    import config
    return config.load_client("avianca")


@pytest.fixture
def ctx_sintetico():
    """Contexto de prueba que no es ningún cliente real. Para los tests del
    MOTOR: si un test del motor necesita saber que existe Avianca, el motor
    todavía está acoplado a un cliente."""
    import config
    market = {
        "slug": "testland", "name": "Testland", "country_code": "TL",
        "language_code": "es", "location_code": 9999,
        "cities": ["Ciudad Uno"], "recognized_media_domains": {"diariotest"},
    }
    sector = {
        "slug": "testsector", "name": "Test Sector",
        "complaint_drivers": ["demora", "otro"],
        "driver_precedence": ["demora", "otro"],
        "driver_glosses": {"demora": "esperas", "otro": "lo demás"},
        "driver_labels": {"demora": "Demoras", "otro": "Otro"},
        "context_words": {"cosa"}, "context_phrases": set(),
        "context_substring_terms": set(), "blacklist_domain_roots": {"spamco"},
        "review_source": "trustpilot",
        "ai_category_prompt_templates": ["¿mejor en {city}?"],
        "ai_brand_prompt_templates": ["¿Es confiable {brand}?"],
        "share_of_voice_problem_terms": ["queja"],
        "share_of_voice_commercial_terms": ["ofertas"],
        "classifier_role": "la empresa {keyword} en {market_name}",
        "has_loyalty_program": False,
    }
    client = {
        "slug": "testclient", "name": "Test Client",
        "market": "testland", "sector": "testsector",
        "own_brand": "Propia", "competitors": [],
        "brands": {"Propia": {"name": "Propia", "keyword": "Propia",
                              "color": "#123456", "domains": set()}},
        "db_path": "data/testclient.db", "deploy_dir": "deploy",
        "report_window_start": "2026-01-01", "backfill_since": "2026-04-19",
    }
    return config.RunContext(client=client, market=market, sector=sector)
```

Los helpers `_market()`/`_sector()`/`_client()` de `tests/test_context.py` (Tarea 1) quedan como están: son locales a ese archivo y sirven para construir perfiles **inválidos** a propósito, cosa que el fixture no permite.

- [ ] **Step 5: Correr toda la suite**

Run: `python -m pytest -q`
Expected: 427 passed (425 + 2). Ninguno previo falla.

- [ ] **Step 6: Commit**

```bash
git add dashboard/ pipeline/ai_visibility.py tests/
git commit -m "refactor: el dashboard recibe el RunContext del cliente"
```

---

## Tarea 10: `--client` obligatorio y borrado de las reexportaciones

Cierra el patrón estrangulador: `config.py` queda solo con motor.

**Files:**
- Modify: `main.py`, `config.py`, `dashboard/build.py` (CLI)
- Test: `tests/test_main.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: Tareas 1-9.
- Produces: `main.run_pipeline(ctx, mode="weekly", since=None, brand_name=None, scrapers=None)`. `config` ya **no** exporta `BRANDS`, `DEFAULT_BRAND`, `get_brand`, `get_ai_prompts`, `get_share_of_voice_keywords`, `COMPLAINT_DRIVERS`, `AVIATION_CONTEXT_*`, `BLACKLIST_DOMAIN_ROOTS`, `RECOGNIZED_MEDIA_DOMAINS`, `AI_VISIBILITY_CATEGORY_PROMPTS`, `AI_VISIBILITY_BRAND_PROMPT_TEMPLATES`, `SHARE_OF_VOICE_*`, `REPORT_WINDOW_START`, `BACKFILL_SINCE`, `DB_PATH`, `COUNTRY_CODE`, `LANGUAGE_CODE`, `LOCATION_CODE`.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_config.py`:

```python
import config

BORRADOS = [
    "BRANDS", "DEFAULT_BRAND", "get_brand", "get_ai_prompts",
    "get_share_of_voice_keywords", "COMPLAINT_DRIVERS",
    "AVIATION_CONTEXT_WORDS", "AVIATION_CONTEXT_PHRASES",
    "AVIATION_CONTEXT_SUBSTRING_TERMS", "BLACKLIST_DOMAIN_ROOTS",
    "RECOGNIZED_MEDIA_DOMAINS", "AI_VISIBILITY_CATEGORY_PROMPTS",
    "AI_VISIBILITY_BRAND_PROMPT_TEMPLATES", "SHARE_OF_VOICE_PROBLEM_TERMS",
    "SHARE_OF_VOICE_COMMERCIAL_TERMS", "REPORT_WINDOW_START",
    "BACKFILL_SINCE", "DB_PATH", "COUNTRY_CODE", "LANGUAGE_CODE",
    "LOCATION_CODE",
]


def test_config_solo_conserva_lo_que_es_motor():
    presentes = [n for n in BORRADOS if hasattr(config, n)]
    assert presentes == [], (
        f"config.py todavía exporta calibración: {presentes}. "
        "Debe vivir en markets/, sectors/ o clients/.")


def test_config_conserva_lo_que_si_es_motor():
    for name in ("DATAFORSEO_LOGIN", "APIFY_API_TOKEN", "DEEPSEEK_API_KEY",
                 "SPANISH_STOPWORDS", "LANG_MIN_WORDS", "LIMIT_DATAFORSEO",
                 "WEB_CHANNEL_RETIREMENT_REASON", "AI_VISIBILITY_MODEL",
                 "INSTAGRAM_POSTS_LIMIT"):
        assert hasattr(config, name), f"config.py perdió {name}, que es motor"
```

Agregar a `tests/test_main.py`:

```python
def test_main_exige_client(capsys):
    import sys
    import main
    with patch.object(sys, "argv", ["main.py"]):
        with pytest.raises(SystemExit):
            main.main()


def test_main_rechaza_client_desconocido():
    import sys
    import main
    with patch.object(sys, "argv", ["main.py", "--client", "no-existe"]):
        with pytest.raises(SystemExit):
            main.main()


def test_main_rechaza_brand_ajena_al_cliente():
    import sys
    import main
    with patch.object(sys, "argv",
                      ["main.py", "--client", "avianca", "--brand", "Wingo"]):
        with pytest.raises(SystemExit):
            main.main()
```

- [ ] **Step 2: Correr para verificar que falla**

Run: `python -m pytest tests/test_config.py tests/test_main.py -q`
Expected: FAIL — `config.py todavía exporta calibración: [...]`

- [ ] **Step 3: Implementar en `main.py`**

```python
    parser.add_argument("--client", required=True,
                        choices=config.available_clients(),
                        help="Cliente sobre el que opera el comando. "
                             "Determina base de datos, mercado, sector y marcas.")
```

Después de parsear:

```python
    ctx = config.load_client(args.client)
    if args.brand is not None and args.brand not in ctx.brands():
        parser.error(
            f"--brand {args.brand!r} no pertenece al cliente {args.client!r}. "
            f"Marcas: {', '.join(ctx.brands())}")
    brand_name = args.brand or ctx.own_brand
    conn = db.connect(ctx.db_path)
```

`--brand` pierde su `default=DEFAULT_BRAND` y pasa a `default=None`.

`run_pipeline` cambia a `run_pipeline(ctx, mode="weekly", since=None, brand_name=None, scrapers=None)` y usa `ctx.sector`, `ctx.market`, `ctx.brand(brand_name)`, `ctx.client["backfill_since"]`.

Actualizar el docstring de cabecera de `main.py` (todos los ejemplos llevan `--client`).

- [ ] **Step 4: Implementar en `dashboard/build.py`**

Su `__main__` gana `--client` obligatorio con las mismas `choices`, y `--brand` se valida contra `ctx.brands()`.

- [ ] **Step 5: Borrar las reexportaciones de `config.py`**

Borrar los tres bloques marcados "se BORRA en la Tarea 10" (Tareas 2, 3 y 4) y las funciones `get_brand`, `get_ai_prompts`, `get_share_of_voice_keywords`.

- [ ] **Step 6: Correr toda la suite**

Run: `PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: 432 passed (427 + 5). Cualquier fallo con `AttributeError: module 'config' has no attribute ...` señala un consumidor que se saltó su tarea de desacople: arreglarlo ahí.

- [ ] **Step 7: Verificar la CLI a mano**

Run: `PYTHONIOENCODING=utf-8 python main.py --help`
Expected: `--client` aparece como requerido con `{avianca}` como opciones.

Run: `PYTHONIOENCODING=utf-8 python main.py --classify`
Expected: error de argparse pidiendo `--client`, sin tocar la base.

- [ ] **Step 8: Commit**

```bash
git add main.py config.py dashboard/build.py tests/
git commit -m "feat: --client obligatorio; config.py queda solo con motor"
```

---

## Tarea 11: Mover los datos de Avianca y verificar la regresión

**La única tarea que toca datos de producción.** Empieza por el respaldo.

**Files:**
- Move: `data/avianca.db` → `clients/avianca/data/avianca.db`; `deploy/*` → `clients/avianca/deploy/`
- Modify: `.gitignore`
- Test: `tests/test_migration_regression.py`, `tests/test_client_isolation.py`

**Interfaces:**
- Consumes: Tareas 1-10.
- Produces: nada nuevo de código; deja el repo en su forma final de Plan A.

- [ ] **Step 1: Respaldar la base**

```bash
mkdir -p data/backups
cp data/avianca.db "data/backups/avianca_$(date +%Y%m%d_%H%M%S)_pre_multicliente.db.bak"
ls -la data/backups/ | tail -3
```
Expected: el respaldo nuevo aparece listado, con el mismo tamaño que `data/avianca.db`.

- [ ] **Step 2: Verificar la regresión del refactor, todavía sin mover nada**

La referencia se congeló en la Tarea 1 Step 0, con el código anterior a todo el refactor. Comparar contra ella **ahora** aísla el efecto de las Tareas 1-10; si algo cambió, es del refactor, no de mover archivos.

```bash
PYTHONIOENCODING=utf-8 python -m dashboard.build --client avianca
PYTHONIOENCODING=utf-8 python - <<'PY'
import re
from pathlib import Path
fecha = re.compile(r"\d{4}-\d{2}-\d{2}")
ref = fecha.sub("FECHA", Path("tests/fixtures/avianca_dashboard_referencia.html").read_text(encoding="utf-8"))
nuevo = sorted(Path("dashboard").glob("avianca_dashboard_*.html"))[-1]
gen = fecha.sub("FECHA", nuevo.read_text(encoding="utf-8"))
print("IDENTICOS" if ref == gen else f"DIFIEREN: {len(ref)} vs {len(gen)} chars")
PY
```
Expected: `IDENTICOS`. **Si dice DIFIEREN, parar acá.** Alguna de las Tareas 2-10 transcribió mal un valor de calibración. Encontrar cuál antes de mover archivos — depurarlo después de la migración es mucho más difícil.

- [ ] **Step 3: Mover los archivos**

```bash
mkdir -p clients/avianca/data clients/avianca/deploy
git mv deploy/vercel.json deploy/robots.txt deploy/.gitignore clients/avianca/deploy/
mv deploy/index.html deploy/latam.html clients/avianca/deploy/ 2>/dev/null || true
mv deploy/.vercel clients/avianca/deploy/ 2>/dev/null || true
mv data/avianca.db clients/avianca/data/avianca.db
rmdir deploy 2>/dev/null || true
```

- [ ] **Step 4: Actualizar `.gitignore`**

Reemplazar las rutas viejas por las nuevas:

```
clients/*/data/*.db
clients/*/data/backups/
clients/*/dashboard/*_dashboard_*.html
clients/*/deploy/index.html
clients/*/deploy/latam.html
```

Borrar `data/*.db`, `dashboard/avianca_dashboard_*.html`, `dashboard/latam_dashboard_*.html`, `deploy/index.html`, `deploy/latam.html`, `data/backups/`.

**Conservar** la línea `!tests/fixtures/avianca_dashboard_referencia.html` que agregó la Tarea 1 Step 0. Si se borra, la referencia de regresión deja de versionarse y el test se salta en silencio (`skipif` sobre el archivo ausente) en cualquier checkout nuevo.

- [ ] **Step 5: Escribir el test de regresión**

Crear `tests/test_migration_regression.py`:

```python
"""
Criterio de éxito del spec §10: la migración no puede cambiar el dashboard.

Compara el HTML regenerado contra el de referencia guardado en el repo,
ignorando solo la fecha de generación.
"""
import re
from pathlib import Path

import pytest

import config

REFERENCIA = Path("tests/fixtures/avianca_dashboard_referencia.html")
FECHA_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _normalizar(html: str) -> str:
    return FECHA_RE.sub("FECHA", html)


@pytest.mark.skipif(not REFERENCIA.is_file(),
                    reason="falta el HTML de referencia")
def test_dashboard_de_avianca_no_cambia_tras_la_migracion(tmp_path):
    from dashboard import aggregate, build
    from store import db

    ctx = config.load_client("avianca")
    if not Path(ctx.db_path).is_file():
        pytest.skip("base de Avianca no disponible en este entorno")

    conn = db.connect(ctx.db_path)
    try:
        generado = build.render(aggregate.build_payload(conn, ctx), ctx)
    finally:
        conn.close()

    assert _normalizar(generado) == _normalizar(
        REFERENCIA.read_text(encoding="utf-8"))
```

- [ ] **Step 6: Correr el test de regresión contra la referencia congelada**

La referencia ya existe y ya está versionada desde la Tarea 1 Step 0 — **no regenerarla**.

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_migration_regression.py -q`
Expected: PASS.

**Si falla, la migración cambió el dashboard.** Encontrar la causa antes de seguir; nunca ajustar la referencia para que el test pase — la referencia es el contrato con el cliente, no un valor esperado que se acomoda.

- [ ] **Step 7: Escribir el test de aislamiento**

Crear `tests/test_client_isolation.py`:

```python
"""Dos clientes en el mismo proceso, sin que uno vea al otro."""
import config


def test_dos_clientes_tienen_bases_distintas():
    slugs = config.available_clients()
    if len(slugs) < 2:
        import pytest
        pytest.skip("hace falta un segundo cliente (Tarea 12)")
    rutas = {s: config.load_client(s).db_path for s in slugs}
    assert len(set(rutas.values())) == len(rutas), f"bases compartidas: {rutas}"


def test_las_marcas_de_un_cliente_no_se_filtran_a_otro():
    slugs = config.available_clients()
    if len(slugs) < 2:
        import pytest
        pytest.skip("hace falta un segundo cliente (Tarea 12)")
    marcas = {s: set(config.load_client(s).brands()) for s in slugs}
    todas = [m for conjunto in marcas.values() for m in conjunto]
    assert len(todas) == len(set(todas)), f"marcas repetidas entre clientes: {marcas}"


def test_cargar_un_cliente_no_altera_el_contexto_de_otro():
    """RunContext es frozen; cargar Avianca dos veces con otro en medio debe
    dar lo mismo."""
    a1 = config.load_client("avianca")
    for slug in config.available_clients():
        config.load_client(slug)
    a2 = config.load_client("avianca")
    assert a1.db_path == a2.db_path
    assert set(a1.brands()) == set(a2.brands())
```

- [ ] **Step 8: Correr toda la suite**

Run: `PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: 436 passed (432 + 4, con los de aislamiento en skip hasta la Tarea 12).

- [ ] **Step 9: Verificar el pipeline a mano, sin gastar API**

Run: `PYTHONIOENCODING=utf-8 python -m dashboard.build --client avianca`
Expected: escribe en `clients/avianca/dashboard/` y el conteo de menciones coincide con el de antes de la migración.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor: aisla los datos y el deploy de Avianca bajo clients/avianca/"
```

---

## Tarea 12: Perfiles de Bolivia, restaurantes y Burger King

Solo configuración. No toca el motor.

**Files:**
- Create: `markets/bolivia.py` (completar el esbozo de la Tarea 7), `sectors/restaurantes.py`, `clients/burger-king-bo/__init__.py`, `clients/burger-king-bo/client.py`
- Test: `tests/test_profiles_contract.py` (ya parametrizado), `tests/test_client_isolation.py` (deja de saltarse)

**Interfaces:**
- Consumes: Tareas 1-11.
- Produces: `config.load_client("burger-king-bo")` funcional y validado.

- [ ] **Step 1: Completar `markets/bolivia.py`**

```python
"""
Mercado Bolivia. location_code verificado contra la API real de DataForSEO
el 2026-08-22 (endpoint locations, costo $0): 2068 para el país, disponible
en serp, business_data y keywords_data. Códigos de departamento por si
alguna vez se necesita granularidad: Cochabamba 20083, La Paz 20084,
Santa Cruz 20085; ciudad de Cochabamba 1001500.
"""

MARKET = {
    "slug": "bolivia",
    "name": "Bolivia",
    "country_code": "BO",
    "language_code": "es",
    "location_code": 2068,
    "cities": ["La Paz", "Santa Cruz", "Cochabamba"],
    # PENDIENTE de calibración: medios bolivianos verificados. Hasta
    # llenarlo, el bloque de prensa clasifica todo como "otro" — es un
    # límite declarado en el spec §12, no un olvido. Se llena con el mismo
    # criterio que Colombia: un dominio entra solo si sus notas SOBRE la
    # marca resultaron genuinamente sobre la marca en datos verificados.
    "recognized_media_domains": set(),
}
```

- [ ] **Step 2: Crear `sectors/restaurantes.py`**

```python
"""
Sector restaurantes. Calibración SEMILLA — andamiaje declarado, no
entregable (spec §8).

Los drivers de abajo son una lista plausible, NO derivada de datos. Los
drivers buenos de aerolíneas salieron de pasar 368 quejas reales por el
clasificador con codebook evolutivo, y ese proceso desmintió una hipótesis
previa y descubrió tres categorías que nadie había anticipado. Aquí falta
hacer exactamente eso — es la fase 7 del spec, en Plan B.
"""

DRIVER_GLOSSES = {
    "pedido_incorrecto": "pedido equivocado, incompleto o con ingredientes que no se pidieron",
    "demora": "espera excesiva en el local, en el auto-servicio o en el delivery",
    "atencion_cliente": "mal trato del personal, falta de respuesta en redes o reclamos sin resolver",
    "calidad_comida": "comida fría, mal preparada, en mal estado o distinta a la publicitada",
    "limpieza": "higiene del local, baños, mesas o utensilios",
    "precios": "precios, promociones que no se respetan, cobros indebidos",
    "delivery": "problemas del pedido a domicilio: no llega, llega tarde, llega mal",
    "app_canales": "fallas de la app propia, la web de pedidos o los canales digitales",
    "otro": "queja real que no encaja en ninguna de las anteriores",
}

SECTOR = {
    "slug": "restaurantes",
    "name": "Restaurantes",
    "complaint_drivers": list(DRIVER_GLOSSES),
    "driver_glosses": DRIVER_GLOSSES,
    # Precedencia semilla: lo que arruina la comida gana sobre lo que
    # rodea al servicio. A recalibrar con datos reales.
    "driver_precedence": [
        "calidad_comida", "pedido_incorrecto", "delivery", "demora",
        "limpieza", "precios", "app_canales", "atencion_cliente", "otro",
    ],
    "driver_labels": {
        "pedido_incorrecto": "Pedido incorrecto", "demora": "Demoras",
        "atencion_cliente": "Atención al cliente",
        "calidad_comida": "Calidad de la comida", "limpieza": "Limpieza",
        "precios": "Precios", "delivery": "Delivery",
        "app_canales": "App y canales digitales", "otro": "Otro",
    },
    # Vocabulario semilla, sin tildes y en minúscula (lo exige el test de
    # contrato: relevance.py compara contra texto ya normalizado).
    "context_words": {
        "hamburguesa", "hamburguesas", "combo", "combos", "papas", "pedido",
        "pedidos", "delivery", "domicilio", "sucursal", "sucursales", "local",
        "locales", "restaurante", "restaurantes", "mesa", "mesas", "menu",
        "comida", "comer", "almuerzo", "cena", "whopper", "cajero", "caja",
        "mostrador", "bandeja", "orden", "ordenes",
    },
    "context_phrases": {"comida rapida", "auto servicio"},
    "context_substring_terms": {"hamburgues", "burger", "delivery"},
    # Arranca VACÍA a propósito. Copiar la lógica de aerolíneas (blacklistear
    # agregadores) sería un error: pedidosya.com.bo aparece como fuente
    # CITADA por la IA al hablar de Burger King — en restaurantes el
    # agregador de delivery es canal legítimo, no ruido SEO. Se llena contra
    # datos reales de la primera corrida.
    "blacklist_domain_roots": set(),
    # Google Business, no Trustpilot: un restaurante vive en Google Maps y
    # tiene un listado POR SUCURSAL. El scraper es Plan B, fase 5.
    "review_source": "google_business",
    # Geográficos a propósito. Verificado con datos reales (2026-08-22): las
    # preguntas que la gente le hace a la IA sobre BK Bolivia son locales
    # ("dónde queda el más cercano", "cómo es el de Calacoto", "existe el de
    # Obrajes"), no reputacionales como en aerolíneas.
    "ai_category_prompt_templates": [
        "¿Dónde comer hamburguesas en {city}?",
        "¿Cuál es la mejor hamburguesería de {city}?",
        "¿Cuáles son los mejores restaurantes de comida rápida en {city}?",
    ],
    "ai_brand_prompt_templates": [
        "¿Cómo es {brand}?",
        "¿Vale la pena comer en {brand}?",
        "Problemas comunes en {brand}",
    ],
    "share_of_voice_problem_terms": ["queja", "reclamo", "intoxicacion", "mala atencion"],
    "share_of_voice_commercial_terms": ["promociones", "menu", "delivery", "sucursales", "horarios"],
    "classifier_role": "la cadena de restaurantes {keyword} en {market_name}",
    "has_loyalty_program": False,
}
```

- [ ] **Step 3: Crear `clients/burger-king-bo/client.py`**

```python
"""
Cliente Burger King Bolivia — restaurantes, Bolivia. Franquicia operada por
Bolivian Foods S.A. (~16 restaurantes desde 1999).

Sin competidores contratados: competitors=[]. Consecuencia declarada (spec
§7): los bloques de share of voice y comparación en IA no tienen contenido
posible y se ocultan. Los bloques de visibilidad en IA de marca propia SÍ
funcionan — verificado el 2026-08-22 contra la API real: 6 menciones,
ai_search_volume 2.950, 10 dominios citados.
"""

CLIENT = {
    "slug": "burger-king-bo",
    "name": "Burger King Bolivia",
    "market": "bolivia",
    "sector": "restaurantes",
    "own_brand": "Burger King",
    "competitors": [],
    "db_path": "data/burger-king-bo.db",
    "deploy_dir": "deploy",
    "report_window_start": "2026-01-01",
    "backfill_since": "2026-04-19",
    "brands": {
        "Burger King": {
            "name": "Burger King",
            "keyword": "Burger King",
            "instagram_profiles": ["https://www.instagram.com/burgerking.bolivia/"],
            "domains": {
                "burgerking.com.bo", "pide.burgerking.com.bo",
                "cmsappbk.burgerking.com.bo",
            },
            # PENDIENTE de validar contra Apify, igual que se hizo con los
            # handles de LATAM (donde dos de los declarados no existían y el
            # scraper devolvía 0 menciones sin error visible).
            "tiktok_hashtags": ["burgerkingbolivia", "burgerkingbo"],
            "tiktok_official_accounts": {"burgerkingbolivia"},
            "loyalty_program": None,
            # Rojo institucional de Burger King. PENDIENTE de confirmar con
            # el cliente; es requerido para construir el dashboard.
            "color": "#D62300",
            "logo": None,
            # PENDIENTE: listados de Google Business por sucursal. Ausente es
            # válido — significa "todavía no se capturan reseñas".
        },
    },
}
```

- [ ] **Step 4: Correr los tests de contrato y aislamiento**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_profiles_contract.py tests/test_client_isolation.py -q`
Expected: PASS. Los tests parametrizados cubren ahora 2 mercados, 2 sectores y 2 clientes; los de aislamiento dejan de saltarse.

- [ ] **Step 5: Verificar que el cliente carga a mano**

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "import config; c=config.load_client('burger-king-bo'); print(c.client['name'], '|', c.market['location_code'], '|', c.sector['review_source'], '|', c.db_path)"
```
Expected: `Burger King Bolivia | 2068 | google_business | ...clients/burger-king-bo/data/burger-king-bo.db`

- [ ] **Step 6: Verificar que la CLI lo reconoce**

Run: `PYTHONIOENCODING=utf-8 python main.py --help`
Expected: `--client {avianca,burger-king-bo}`

- [ ] **Step 7: Correr toda la suite**

Run: `PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: ~445 passed. Ninguno falla.

- [ ] **Step 8: Commit**

```bash
git add markets/bolivia.py sectors/restaurantes.py clients/burger-king-bo/ tests/
git commit -m "feat: perfiles de Bolivia, restaurantes y Burger King Bolivia"
```

---

## Cierre de Plan A

Verificaciones finales antes de dar el plan por terminado:

- [ ] `PYTHONIOENCODING=utf-8 python -m pytest -q` — todo verde
- [ ] `python -m pytest tests/test_migration_regression.py -q` — el dashboard de Avianca no cambió
- [ ] `grep -rn "^from config import\|^import config" --include=*.py . | grep -v tests/` — ningún módulo del motor importa calibración; solo credenciales, límites y recursos de idioma
- [ ] `PYTHONIOENCODING=utf-8 python main.py --client avianca --help` corre; sin `--client` falla
- [ ] `README.md` actualizado: todos los comandos llevan `--client`, y la tabla de variables de entorno ya no menciona `BRAND_KEYWORD`/`COUNTRY_CODE`/`LANGUAGE_CODE`/`LOCATION_CODE`
- [ ] `.env.example` actualizado: solo credenciales

**Lo que Plan A NO entrega, por diseño:** ninguna captura real de Burger King, el scraper de Google Business, la columna `branch`, el marcador `__DRIVER_LABELS__` ni los drivers de restaurantes recalibrados. Todo eso es Plan B (fases 5-7 del spec).
