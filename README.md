# 🌊 Caribbean Marine Intelligence

Monitoring, oceanographic and weather analysis, and tropical cyclone tracking for the Caribbean, with an initial focus on
**Providencia y Santa Catalina, Colombia** . 
Python + Streamlit, 100 % fuentes públicas/gratuitas, sin claves ni base de datos de pago.

> This platform is an independent data visualization and analytics project. It does not replace official
> meteorological, maritime or emergency warnings.


## Fuentes (verificadas contra su documentación)

| Fuente | Mecanismo |
|---|---|
| Open-Meteo Marine / Weather | REST `marine-api.open-meteo.com/v1/marine`, `api.open-meteo.com/v1/forecast` (+ `archive-api` para histórico) |
| NOAA NHC | `https://www.nhc.noaa.gov/CurrentStorms.json` → zips GIS (cono, track, warnings, radios, best track); HURDAT2 (el nombre del archivo cambia con cada versión: se descubre dinámicamente) |
| NOAA NCEI ERDDAP | `/erddap/search`, `/info`, `/tabledap`, `/griddap` → CSV → DataFrame. Los dataset IDs se buscan en vivo, no están fijos |
| GDACS (ONU / Comisión Europea) | `https://www.gdacs.org/gdacsapi/api` (sin clave): ciclones de **todas** las cuencas (Asia, Índico, Oceanía), con datos JTWC/NOAA. NHC manda dentro de sus cuencas; GDACS cubre el resto |
| NASA GIBS | Mosaico satelital diario VIIRS a color real como fondo del mapa (`gibs.earthdata.nasa.gov/wmts`) |

El nivel del mar proviene del modelo de Open-Meteo y se rotula como tal. (La carga de archivos DIMAR/CECOLDO se retiró de la interfaz a petición del proyecto.)

## Novedades de la interfaz

- **Rastreador mundial de ciclones** estilo app: todos los sistemas activos del planeta (NHC + GDACS) en un mapa con fondo satelital real de NASA, cono y warnings oficiales (cuencas NHC), trayectorias, posiciones pronosticadas, selector de región (Auto / World / Asia / Índico / Oceanía…) y datos al pasar el cursor o tocar cada tormenta.
- **Gráficos con zonas de color** (cómodo / precaución / difícil / peligroso), medidores, brújula de viento y marcador *Now*.
- **Anomalías explicadas**: banda verde de rango normal, etiquetas *Normal / Unusual / Very unusual* y un resumen en lenguaje simple.
- Unidades duales (m/ft, kn/mph/km/h) y glosario en cada página.

## Estructura

```
app.py                  navegación, tema, sidebar
pages/                  dashboard · hurricanes · ocean · weather · sea_level · analysis · historical · about
services/               base (HTTP+retries+timeouts) · open_meteo_* · noaa_nhc · gdacs · noaa_erddap
analytics/              statistics · anomalies · risk · forecasting · cyclones · report
utils/                  config (paleta, ubicaciones) · data (st.cache_data) · cache (SQLite/Parquet) · ui · maps · export · coordinates · formatting
tests/                  unitarias + humo de páginas (con y sin red) + parser de shapefiles
```
Nota: la página `analytics` del esquema original se llama `pages/analysis.py` porque un archivo `pages/analytics.py`
colisiona con el paquete `analytics/` en `sys.path`.

## Decisiones de diseño

- **Oficial vs calculado:** todo lo del NHC (posición, cono, track, watches/warnings) se rotula *OFFICIAL · NOAA/NHC*;
  distancias, rumbo, tendencia y aproximación mínima se rotulan *COMPUTED*.
- **Un fallo no rompe nada:** cada fuente devuelve `FetchResult`; si falla se muestra *Data unavailable*. Las excepciones
  no se cachean.
- **Caché por fuente:** marino 30 min, clima 15 min, NHC 10 min, HURDAT2 7 días, ERDDAP 1 h.
- **Historial local:** observaciones Open-Meteo → SQLite con clave primaria (deduplicación idempotente).
- **Punto marino:** si la celda exacta es tierra/enmascarada, se prueban puntos de mar cercanos y se avisa en la UI.
- **Riesgo marino:** reglas transparentes y editables en el sidebar; no es información oficial.
- **Paleta tropical/azul:** `utils/config.py::PALETTE` y `.streamlit/config.toml`.

## Licencias y uso comercial

La API gratuita de Open-Meteo es para **uso no comercial** (atribución CC BY 4.0); para ofrecer esto a hoteles/empresas
hace falta su plan comercial. Mapas: imágenes NASA GIBS (uso libre con atribución) y estilos Carto (el código ya lee claves desde `st.secrets`/entorno).

## Hoja de ruta

Alertas por correo/Telegram, boyas NDBC/ERDDAP en el mapa, UHSLC para nivel del mar, i18n ES/EN, PDF del reporte.
