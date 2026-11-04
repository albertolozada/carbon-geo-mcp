# Guía de uso de carbon-geo-mcp (Windows)

Esta guía explica qué es carbon-geo-mcp, cómo instalarlo y cómo usarlo con Claude Desktop, con Claude Code (CLI) o directamente desde Python. Los ejemplos usan Windows y la carpeta `E:\Proyectos`; cámbiala por la tuya.

## 1. Para qué sirve

carbon-geo-mcp es un **servidor MCP** (Model Context Protocol): una caja de herramientas SIG que un asistente de IA puede usar por su cuenta. Hay dos piezas:

- **El host**: la aplicación donde escribes (Claude Desktop, Claude Code, Cursor...).
- **El servidor**: carbon-geo-mcp, un pequeño programa Python que corre **en tu ordenador**.

Cuando preguntas, por ejemplo, "¿coinciden las áreas del shapefile con las del PD?", el asistente elige una herramienta, tu ordenador ejecuta el cálculo real con GeoPandas o Rasterio sobre el archivo, y el asistente recibe un resumen corto y lo explica. El modelo no inventa cifras, y cada resultado indica **el CRS utilizado** y **qué datos faltaban**.

| Pregunta | Herramienta |
|---|---|
| "¿Este shapefile está en grados? ¿Tiene geometrías inválidas?" | `layer_info` |
| "¿Cuántas hectáreas tiene cada estrato?" | `area_by_stratum` |
| "El PD declara 12.500 ha, ¿coincide?" | `compare_declared_area` |
| "¿Solapa con áreas protegidas u otro proyecto?" | `check_overlap` |
| "¿Hay parcelas fuera de su estrato o duplicadas?" | `plots_in_strata` |
| "¿Cuánto bosque se perdió en el periodo de monitoreo?" | `forest_loss_in_area` |
| "¿Qué campos de la base de parcelas están incompletos?" | `data_completeness` |

Reglas que aplican todas las herramientas:

- Nunca se mide en grados. Las áreas se calculan en una proyección de igual área (Lambert Azimutal centrada en los datos) y las distancias en la zona UTM local.
- Los polígonos se disuelven antes de medir, así que no se cuenta dos veces la misma superficie; los solapamientos se informan.
- Un resultado de 0 (sin solapamiento, sin pérdida) es un resultado real, y los errores (archivo inexistente, campo inexistente) se devuelven como errores explícitos.
- El servidor es local y de solo lectura: no escribe ni envía archivos.

**Importante:** el servidor no se abre ni se usa por sí solo. Lo arranca el host cuando lo necesita. Si lo ejecutas a mano en una terminal, se queda quieto esperando, y eso es lo normal.

## 2. Instalación (una sola vez)

### Paso 1. Instalar uv

uv es un gestor que descarga Python y las librerías por ti. En PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Cierra y vuelve a abrir PowerShell, y comprueba la instalación:

```powershell
uvx --version
where.exe uvx
```

Anota la ruta que devuelve `where.exe` (normalmente `C:\Users\TU_USUARIO\.local\bin\uvx.exe`).

### Paso 2. Instalar Git (si no lo tienes)

```powershell
winget install Git.Git
```

### Paso 3. Descargar y probar el servidor por primera vez

La primera ejecución descarga Python 3.12, GeoPandas, Rasterio y el resto de dependencias (unos 150 MB), así que conviene hacerla antes de conectarlo a ningún host:

```powershell
uvx --python 3.12 --from git+https://github.com/albertolozada/carbon-geo-mcp carbon-geo-mcp
```

Cuando aparezca una línea de log y el cursor se quede quieto, el servidor está funcionando. Sal con **Ctrl+C**. Las siguientes veces arrancará en segundos.

## 3. Cómo usarlo

### Opción A. Claude Desktop

1. En Claude Desktop, abre **Settings → Developer → Edit Config**. Se abre `claude_desktop_config.json` (normalmente en `%APPDATA%\Claude\`).
2. Pega este bloque, cambiando `TU_USUARIO` y la carpeta de proyectos:

```json
{
  "mcpServers": {
    "carbon-geo-mcp": {
      "command": "C:\\Users\\TU_USUARIO\\.local\\bin\\uvx.exe",
      "args": ["--python", "3.12", "--from", "git+https://github.com/albertolozada/carbon-geo-mcp", "carbon-geo-mcp"],
      "env": { "CARBON_GEO_MCP_ROOTS": "E:\\Proyectos" }
    }
  }
}
```

   - Dentro del JSON las barras invertidas van **dobles** (`\\`).
   - Se usa la ruta completa de `uvx.exe` porque Claude Desktop a veces no encuentra programas que están en el PATH.
   - `CARBON_GEO_MCP_ROOTS` limita el servidor a esa carpeta y no podrá leer nada fuera de ella. Para varias carpetas, sepáralas con `;` (por ejemplo `"E:\\Proyectos;D:\\GIS"`).
   - Si el archivo ya tiene otros servidores, añade el bloque `"carbon-geo-mcp": {...}` dentro del `mcpServers` existente.
3. **Cierra Claude Desktop del todo**, también desde el icono de la bandeja del sistema, y vuelve a abrirlo.
4. En una conversación nueva, el icono de herramientas debe mostrar `carbon-geo-mcp` con sus 7 herramientas.

### Opción B. Claude Code (CLI)

Registra el servidor con un solo comando. Con `--scope user` queda disponible en todos tus proyectos:

```powershell
claude mcp add carbon-geo-mcp --scope user -e CARBON_GEO_MCP_ROOTS=E:\Proyectos -- uvx --python 3.12 --from git+https://github.com/albertolozada/carbon-geo-mcp carbon-geo-mcp
```

Comprueba que está registrado:

```powershell
claude mcp list
```

Después entra en la carpeta del proyecto y lanza Claude Code:

```powershell
cd E:\Proyectos\MiProyecto
claude
```

Dentro de la sesión, `/mcp` muestra el estado del servidor. Esta opción es práctica porque Claude Code trabaja sobre la carpeta del proyecto: puede listar los shapefiles, pasar las rutas al servidor y redactar el resultado en un archivo.

### Opción C. Sin IA: MCP Inspector o Python

**MCP Inspector** (requiere [Node.js](https://nodejs.org)) abre una página web donde se ejecuta cada herramienta rellenando un formulario. Es útil para comprobar resultados:

```powershell
npx @modelcontextprotocol/inspector uvx --python 3.12 --from git+https://github.com/albertolozada/carbon-geo-mcp carbon-geo-mcp
```

**Como librería Python**, desde un notebook o un script:

```python
from carbon_geo_mcp import geo

geo.compare_declared_area(
    r"E:\Proyectos\MiProyecto\estratos.shp",
    declared_ha={"total": 12500},
    stratum_field="estrato",
)
```

## 4. Primera prueba con los datos de ejemplo

1. Descarga el repositorio (botón verde **Code → Download ZIP**) y descomprímelo dentro de la carpeta autorizada, por ejemplo `E:\Proyectos\demo`.
2. Pide al asistente:

```text
Usa carbon-geo-mcp con los archivos de E:\Proyectos\demo\carbon-geo-mcp-main\data\sample.
1. Ejecuta layer_info en cada capa y dime cuáles están en grados.
2. El PD declara 8.000 ha en total, 4.800 de dense_forest y 2.800 de open_forest
   (campo "stratum"). Compáralo con project_strata.gpkg con tolerancia del 1 %.
3. Revisa plots.gpkg contra los estratos: parcelas fuera, con estrato erróneo
   o a menos de 50 m del borde.
4. Calcula la pérdida de bosque 2015-2024 con lossyear_sample.tif.
Indica siempre el CRS utilizado.
```

Resultado esperado (los datos son ficticios y los problemas están puestos a propósito):

- 50 ha de solapamiento entre estratos.
- `open_forest` con un 1,8 % más de área que la declarada.
- 2 parcelas fuera de los estratos, 1 con el estrato equivocado, 1 a 20 m del borde y 1 par de coordenadas duplicadas.
- 289 ha de pérdida de bosque en 2015-2024.

## 5. Uso en una auditoría real

1. Copia las capas del proyecto a una carpeta dentro de la carpeta autorizada.
2. Para la pérdida de bosque, descarga la tesela `lossyear` de Hansen Global Forest Change que cubre el proyecto (ver [`data/README.md`](../data/README.md)).
3. Pide las comprobaciones en lenguaje normal, indicando los valores del PD o del informe de monitoreo.
4. Confirma por tu cuenta (en QGIS o con el notebook) cualquier cifra que vaya a un hallazgo o a un informe. La herramienta acelera la exploración, pero no sustituye la verificación del auditor.

**Confidencialidad:** los archivos no salen de tu ordenador, pero los resúmenes que devuelve el servidor (hectáreas, nombres de estratos, IDs de parcelas) sí llegan al modelo de IA. Antes de usarlo con datos de clientes, comprueba que la política de tu organización lo permite.

## 6. Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| No aparece en Claude Desktop | Revisa el log en `%APPDATA%\Claude\logs\mcp-server-carbon-geo-mcp.log`. Causas habituales: barras sin duplicar en el JSON, ruta de `uvx.exe` incorrecta o la app no se cerró del todo. |
| Se queda cargando la primera vez | Está descargando las librerías. Ejecuta antes el comando del paso 3 de la instalación. |
| Error "outside the folders this server may read" | El archivo está fuera de `CARBON_GEO_MCP_ROOTS`. Muévelo a la carpeta autorizada o amplía la lista. |
| Error de CRS en un shapefile | Faltan archivos acompañantes. La carpeta debe contener el `.shp` con su `.shx`, `.dbf` y `.prj`; sin el `.prj` el servidor no mide porque no conoce el CRS. |
| Quiero la última versión | Ejecuta `uv cache clean` y reinicia el host. |
