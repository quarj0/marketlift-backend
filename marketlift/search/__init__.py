from .contracts import SearchRequest


def search_listings(*args, **kwargs):
    # Lazy import keeps parser/normalization utilities usable without loading the
    # Django model registry and avoids unnecessary startup coupling.
    from .service import search_listings as _search_listings

    return _search_listings(*args, **kwargs)


__all__ = ["SearchRequest", "search_listings"]
