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
