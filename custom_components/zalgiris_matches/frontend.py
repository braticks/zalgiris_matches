from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

CARD_URL = f"/{DOMAIN}/zalgiris-card.js"
CARD_PATH = Path(__file__).parent / "www" / "zalgiris-card.js"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve and register the bundled Žalgiris Lovelace card."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), False)]
    )

    integration = await async_get_integration(hass, DOMAIN)
    versioned_url = f"{CARD_URL}?v={integration.version}"

    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        add_extra_js_url(hass, versioned_url)
        return

    resources = lovelace.resources

    # Storage mode is Home Assistant's default. Force the collection to load
    # before reading/creating items so existing resources are never overwritten.
    if isinstance(resources, ResourceStorageCollection):
        await resources.async_get_info()

        for resource in resources.async_items():
            resource_url = str(resource.get("url", ""))
            if resource_url.split("?", 1)[0] != CARD_URL:
                continue

            if resource_url != versioned_url or resource.get("res_type") != "module":
                await resources.async_update_item(
                    resource["id"],
                    {"res_type": "module", "url": versioned_url},
                )
            return

        await resources.async_create_item(
            {"res_type": "module", "url": versioned_url}
        )
        return

    # YAML resource mode cannot be modified through storage.
    add_extra_js_url(hass, versioned_url)
