# Nextcloud Memories ESP32

![Icono de Nextcloud Memories ESP32](custom_components/nextcloud_memories/brand/icon.png)

Integración comunitaria para **Home Assistant** que utiliza álbumes de **Nextcloud Memories** como fuente de fotografías para marcos digitales basados en **ESPHome/ESP32**.

> Proyecto independiente; no es una integración oficial de Home Assistant ni del proyecto Nextcloud Memories.

## Qué hace

- Conecta Home Assistant con Nextcloud Memories mediante su API local.
- Permite seleccionar álbumes y asociarlos a marcos lógicos vinculados con dispositivos ESPHome existentes.
- Gestiona fotografías en caché, prefetch, orden aleatorio, avance/retroceso y rotación automática.
- Admite JPEG y BMP24, tamaño por dispositivo y control opcional de retroiluminación vinculado a una entidad de presencia.
- Crea sensores de estado, botones para fotografía siguiente/anterior y mezcla de fotografías, y un control numérico de intervalo de rotación.

## Requisitos

- Home Assistant con soporte para integraciones personalizadas.
- Nextcloud con la aplicación **Memories** instalada y accesible por red **desde Home Assistant**; no tiene que ser accesible desde Internet.
- Usuario de Nextcloud y una contraseña de aplicación/token con acceso a los álbumes deseados.
- Para mostrar imágenes, un ESP32 con ESPHome y una pantalla configurada para solicitar las URL de las imágenes servidas por Home Assistant. **No incluye firmware ESPHome**.

## Instalación con Marketplace / HACS

1. Abre **Settings → Marketplace** (o **HACS** en versiones anteriores).
2. Añade este repositorio como **custom repository** de tipo **Integration**: `fherreror/ha-nextcloud-memories-esp32`.
3. Instala **Nextcloud Memories**, reinicia Home Assistant y añádela desde **Settings → Devices & services → Add integration**.
4. Introduce la URL base de Nextcloud, usuario y token. Mantén activada la verificación SSL salvo que estés probando un certificado no válido.
5. Desde las opciones de la integración, crea los dispositivos de marco y selecciona los álbumes y dispositivos ESPHome correspondientes.

## Configuración paso a paso

La integración se configura **desde Home Assistant**. No hace falta editar archivos YAML ni publicar Nextcloud en Internet. Hay dos partes: **conexión con Nextcloud Memories** y **configuración de cada marco ESP32**.

### 1. Preparar Nextcloud

1. Comprueba que la aplicación **Memories** funciona en tu servidor Nextcloud y que el usuario puede abrir los álbumes que quieres mostrar.
2. Prepara el **nombre de usuario** y una **contraseña de aplicación** de Nextcloud (preferible a usar la contraseña habitual). Puedes crearla en los ajustes de seguridad de tu cuenta.
3. Anota la **URL base de Nextcloud**, tal como la alcanza Home Assistant desde su propia red. Por ejemplo: `https://nextcloud.example.test` o una dirección interna accesible desde Home Assistant. Es la URL de Nextcloud, **no** la ruta `/apps/memories`.

> El servidor Nextcloud solo necesita ser accesible desde Home Assistant. El ESP32 obtendrá las fotografías preparadas de Home Assistant, no directamente de Nextcloud.

### 2. Conectar la integración a Nextcloud

1. En Home Assistant abre **Ajustes → Dispositivos y servicios → Añadir integración** y busca **Nextcloud Memories**.
2. Completa los campos del asistente:

| Campo | Qué introducir |
|---|---|
| **Nextcloud base URL** | Dirección base que Home Assistant utiliza para acceder a Nextcloud, con `http://` o `https://`. |
| **Username** | Usuario de Nextcloud que tiene acceso a los álbumes. |
| **API token** | Contraseña de aplicación/token de ese usuario. |
| **Verify SSL certificate** | Déjalo activado si el certificado HTTPS es válido y confiable. Desactivarlo reduce la seguridad de la conexión. |
| **Image base URL** | Dirección **de Home Assistant** que podrá abrir el ESP32, por ejemplo `http://homeassistant.local:8123` si ese nombre resuelve correctamente en el dispositivo. |

3. Guarda. La integración comprueba la conexión con la API de Nextcloud Memories antes de crear la entrada.

**Atención: hay dos URL diferentes.** `Nextcloud base URL` se usa para descargar las imágenes desde Nextcloud hacia Home Assistant; `Image base URL` se usa para construir las URL que consulta el ESP32 en Home Assistant. Si `homeassistant.local` no se resuelve desde el ESP32, utiliza una dirección LAN de Home Assistant alcanzable desde el dispositivo. No incluyas `/local/...` en el valor de `Image base URL`.

### 3. Crear y vincular un marco ESP32

1. Asegúrate de que el dispositivo ESP32 ya está configurado en **ESPHome**, integrado en Home Assistant y dispone de una pantalla capaz de cargar imágenes por URL HTTP.
2. En **Ajustes → Dispositivos y servicios**, abre **Nextcloud Memories** y entra en **Configurar / Opciones**.
3. En **Action**, selecciona **Create**. También puedes ajustar aquí la **Image base URL**.
4. En el formulario **Frame Device**, rellena estos campos y guarda:

| Campo | Función | Valor inicial |
|---|---|---|
| **Device key** | Identificador único del marco dentro de la integración; usa letras, números, `_`, `-` o `.`. | Obligatorio; por ejemplo `marco_salon` |
| **ESP device id** | Selecciona el ESPHome existente. La lista se genera a partir del `device_name` de las entradas de ESPHome; también admite un valor personalizado. | Seleccionar el dispositivo |
| **Friendly name** | Nombre visible en Home Assistant para el marco lógico. | Identificador del marco |
| **Album IDs** | Uno o varios álbumes de Memories; se pueden elegir en la lista o introducir sus identificadores. | Obligatorio (al menos uno) |
| **Width / Height** | Resolución de la imagen que se genera para la pantalla. | 800 × 480 |
| **Image format** | `jpeg` (JPEG baseline) o `bmp24` (BMP de 24 bits). Debe ser compatible con el decodificador de tu ESP32. | `jpeg` |
| **Randomize** | Mezcla las fotografías de los álbumes seleccionados. | Activado |
| **Max photos** | Máximo de fotografías por álbum que se incluyen al cargar la lista. | 500 |
| **Max cache files** | Número máximo de imágenes que se mantienen en caché para ese marco. | 80 |
| **Prefetch each side** | Fotografías anteriores y siguientes que se preparan alrededor de la actual. | 5 |
| **Rotation minutes** | Intervalo de avance automático (entre 1 y 30 minutos). | 10 |
| **Presence entity for LCD backlight** | Entidad `binary_sensor` o `input_boolean` opcional para encender/apagar la retroiluminación en función de `on`/`off`. | Sin seleccionar |

**Diferencia entre los identificadores:** `Device key` identifica el marco lógico en Nextcloud Memories; `ESP device id` identifica el ESPHome físico vinculado. No tienen por qué ser iguales. Un mismo `ESP device id` no puede asignarse a dos marcos de esta integración.

**Álbumes:** se admiten varios álbumes para un mismo marco. El selector consulta Nextcloud para mostrar sus nombres e identificadores; un identificador habitual es `usuario/Nombre del álbum`. Si no se puede cargar la lista, el formulario conserva las selecciones ya guardadas. Comprueba que el usuario de Nextcloud tiene acceso a los álbumes.

**Presencia:** para controlar la retroiluminación debe existir en el dispositivo ESPHome un interruptor `switch` identificado por Home Assistant cuyo nombre incluya **backlight**; la integración prefiere uno que incluya además **lcd**. Solo actúa ante `on` y `off`. Este ajuste no crea por sí mismo el interruptor físico.

### 4. Comprobar el marco y manejar las fotografías

Al guardar un marco, Home Assistant recarga la integración y crea las entidades asociadas. Entre ellas:

- Un **sensor de fotografías** cuyo estado es `idle` o el identificador `fileid` de la fotografía actual. Sus atributos incluyen `current_url`, `prev_url`, `next_url`, `count`, `index` y los álbumes.
- Tres **botones** para **Next Photo**, **Previous Photo** y **Regenerate Random**.
- Un **control numérico** **Rotation Minutes** para modificar el intervalo de rotación.

Para probar el servicio manualmente, abre **Herramientas para desarrolladores → Acciones** en Home Assistant, elige **Nextcloud Memories: Frame refresh** e indica el `device_key` configurado. Por ejemplo, en el editor YAML de una acción:

```yaml
action: nextcloud_memories.frame_refresh
data:
  device_key: marco_salon
  direction: stay
```

La respuesta del servicio contiene las URL `current.url`, `prev.url` y `next.url`, así como el índice y la cantidad de fotos. La integración también publica URL de fotografías en los **atributos del sensor**.

**Importante:** vincular un ESPHome en el formulario no instala ni modifica su firmware. El ESP32 debe tener su propio código ESPHome para recuperar y mostrar las imágenes de Home Assistant (por ejemplo, mediante `online_image` o el mecanismo que utilice tu pantalla). La integración gestiona las fotos, la caché y el estado del marco en Home Assistant.

### 5. Editar o eliminar un marco

Abre de nuevo **Nextcloud Memories → Configurar / Opciones**:

- **Edit**: elige el dispositivo en **Target device** y modifica sus álbumes, resolución, tiempo de rotación, etc.
- **Delete**: selecciona el dispositivo y elimínalo de los marcos configurados. **No elimina el ESPHome físico** de Home Assistant.

También existen las acciones avanzadas `frame_device_set`, `frame_device_list` y `frame_device_delete`, descritas más abajo.

### Solución de problemas

| Síntoma | Comprobaciones |
|---|---|
| **Cannot connect / Invalid authentication** | Verifica la URL base, conexión de Home Assistant con Nextcloud, usuario, contraseña de aplicación y certificado SSL. |
| **No aparecen álbumes en la lista** | Abre Memories con ese usuario, comprueba permisos y revisa los registros de Home Assistant. |
| **El marco aparece, pero el ESP32 no muestra fotografías** | Comprueba que su firmware carga las URL de Home Assistant, que `Image base URL` resuelve y que la pantalla soporta el formato y tamaño elegidos. |
| **La imagen está en los atributos del sensor, pero da error HTTP** | Comprueba el acceso de red del ESP32 a Home Assistant y la existencia del archivo en `/config/www/nextcloud_memories/`. |
| **No se enciende o apaga la retroiluminación por presencia** | Verifica que el ESPHome tiene el `switch` de backlight y que el sensor seleccionado realmente cambia entre `on` y `off`. |
| **Las fotos no se actualizan** | Prueba **Regenerate Random** o `frame_refresh` con `force_reload: true`; comprueba los atributos `album_errors` del sensor. |

### Si ya se había instalado manualmente

**No elimines la integración en Devices & services**, porque eso podría borrar sus entradas de configuración. Haz primero una copia de seguridad completa de Home Assistant (incluida `.storage`). Comprueba que la integración instalada usa el dominio `nextcloud_memories` y haz que Marketplace gestione la carpeta existente de `/config/custom_components/nextcloud_memories`; evita dos copias simultáneas. Reinicia y comprueba la configuración antes de continuar.

## Servicios

Los servicios disponibles figuran en [services.yaml](custom_components/nextcloud_memories/services.yaml):

| Servicio | Función |
|---|---|
| `nextcloud_memories.get_albums` | Lista álbumes de Nextcloud Memories |
| `nextcloud_memories.get_photo_list` | Recupera metadatos de fotografías de un álbum |
| `nextcloud_memories.get_photo` | Descarga y prepara una fotografía |
| `nextcloud_memories.frame_refresh` | Cambia o actualiza la imagen del marco |
| `nextcloud_memories.frame_reset` | Reinicia el estado de un marco |
| `nextcloud_memories.frame_device_set` | Crea o actualiza la configuración de un marco |
| `nextcloud_memories.frame_device_list` | Lista marcos configurados |
| `nextcloud_memories.frame_device_delete` | Elimina la definición de un marco |

Los parámetros completos se muestran en la interfaz de acciones/servicios de Home Assistant.

## Almacenamiento y privacidad

- Las credenciales se almacenan en la configuración local de Home Assistant, **no en el repositorio**.
- Las definiciones de marcos se almacenan en la carpeta protegida `.storage` de Home Assistant; **no se guardan dentro de `custom_components`** y no se deben subir a GitHub.
- Las imágenes preparadas se guardan en `/config/www/nextcloud_memories/` y se sirven mediante `/local/nextcloud_memories/`. **Las URL de `/local/` pueden ser accesibles sin autenticación a cualquiera que tenga acceso HTTP a Home Assistant.** Configura tu red y tus proxies teniendo esto en cuenta y evita álbumes sensibles.
- No es necesario exponer Nextcloud a Internet para usar esta integración. Si el ESP32 puede acceder al servidor de Home Assistant por LAN, configura una `image_base_url` accesible para el ESP32.

## Desarrollo y pruebas (sin un servidor Nextcloud)

El proyecto contiene [tests](tests/) con respuestas simuladas de API. No hacen conexiones reales ni requieren credenciales. La validación de integración y repositorio se ejecuta automáticamente en **GitHub Actions** al subir cambios o abrir pull requests.

Para ejecutar los tests localmente (Python 3.13): instala `pytest`, `aiohttp` y `pyyaml`, y ejecuta `pytest -q` desde la raíz. La integración que se instala en HA no requiere `pytest`.

Los tests verifican normalización de álbumes/fotos, autenticación preparada, construcción de solicitudes y consistencia de archivos de empaquetado; no garantizan compatibilidad con todas las versiones de la API Nextcloud Memories ni prueban el ESP32 físico.

## Versiones y actualizaciones

Se usa versionado semántico `MAJOR.MINOR.PATCH`. El campo `version` de `manifest.json` debe coincidir con cada GitHub Release publicada (por ejemplo, tag `v0.1.0` y versión `0.1.0`). El Marketplace/HACS puede detectar nuevas versiones y descargarlas; normalmente se necesita reiniciar Home Assistant.

Consulta [CHANGELOG.md](CHANGELOG.md) para ver los cambios. Abre un [issue](https://github.com/fherreror/ha-nextcloud-memories-esp32/issues) para informar de errores **sin compartir tokens, IP privadas ni fotografías**.

## Licencia

[MIT](LICENSE).
