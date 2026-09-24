"""Provider lookup. Adding a farm is one module plus one line in _PROVIDERS."""
from typing import Dict, List

from .base import FarmProvider, UnsupportedOperation
from .browserstack import BrowserStackProvider
from .lambdatest import LambdaTestProvider
from .saucelabs import SauceLabsProvider

_PROVIDERS: Dict[str, type] = {
    SauceLabsProvider.name: SauceLabsProvider,
    BrowserStackProvider.name: BrowserStackProvider,
    LambdaTestProvider.name: LambdaTestProvider,
}

#: Providers whose REST half (app upload, device pool, artifacts) is implemented.
FULLY_IMPLEMENTED = (SauceLabsProvider.name,)


def provider_names() -> List[str]:
    return sorted(_PROVIDERS)


def get_provider(name: str) -> FarmProvider:
    """Instance for `name`, or ValueError naming what is available."""
    key = (name or '').strip().lower()
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise ValueError(
            f"unknown device farm provider {name!r} - known: {', '.join(provider_names())}")
    return cls()


__all__ = ['FarmProvider', 'UnsupportedOperation', 'get_provider',
           'provider_names', 'FULLY_IMPLEMENTED']
