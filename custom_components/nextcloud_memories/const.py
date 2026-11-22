"""Constants for the Nextcloud Memories integration."""

DOMAIN = "nextcloud_memories"

CONF_BASE_URL = "base_url"
CONF_USERNAME = "username"
CONF_API_TOKEN = "api_token"
CONF_VERIFY_SSL = "verify_ssl"
CONF_IMAGE_BASE_URL = "image_base_url"
CONF_ENTRY_ID = "entry_id"

DEFAULT_VERIFY_SSL = True
DEFAULT_MAX_PHOTOS = 50
DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 480
DEFAULT_ROTATION_MINUTES = 10

SERVICE_GET_ALBUMS = "get_albums"
SERVICE_GET_PHOTO_LIST = "get_photo_list"
SERVICE_GET_PHOTO = "get_photo"
SERVICE_FRAME_REFRESH = "frame_refresh"
SERVICE_FRAME_RESET = "frame_reset"
SERVICE_FRAME_DEVICE_SET = "frame_device_set"
SERVICE_FRAME_DEVICE_DELETE = "frame_device_delete"
SERVICE_FRAME_DEVICE_LIST = "frame_device_list"

CACHE_DIR_NAME = "nextcloud_memories"
SIGNAL_FRAME_STATE_PREFIX = "nextcloud_memories_frame_state"
