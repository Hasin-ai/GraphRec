"""The credential, holding the secret where nothing can print it."""

from __future__ import annotations

from .errors import ConfigurationError

#: `PREFIX_NAMESPACE`, `graphrec/auth/api_keys.py`. Note: `gr_live_`, not
#: `grk_live_` — the console's /integration page prints the latter and is wrong
#: (§12 of the design doc), which is exactly the kind of mistake a client should
#: refuse loudly rather than send.
PREFIX_NAMESPACE = "gr_live_"
_SEPARATOR = "."


class Credential:
    """A GraphRec API credential.

    The credential is ``gr_live_XXXX.<43 url-safe characters>``
    (`graphrec/auth/api_keys.py`). The prefix is a **public identifier** — the
    console prints it in the credentials table and the server logs it as the
    actor on every request — and all 256 bits of entropy are after the
    separator.

    **The secret lives behind name mangling and a `__slots__` layout with no
    `__dict__`, and the dunders that render an object are overridden.** Python
    cannot make a field genuinely private, so this cannot be as strong as the
    TypeScript SDK's `#private` field. What it can do is close every path that
    prints an object by accident: `repr`, `str`, `pprint` and the `%r` in a log
    format all go through `__repr__`; `logging`'s `extra` and most structured
    loggers go through `__dict__`, which is absent; and `copy`/`pickle` are
    refused rather than allowed to write the secret to a file. Reading it still
    works — `credential._Credential__secret` — and is meant to require a person
    to have decided to.

    **Not a request signature.** `apps/inference/deps.py` reads the credential
    through `fastapi.security.HTTPBearer` and `apps/control_api/deps.py` does
    the same; the HMAC-SHA-256 in `api_keys.py` hashes the secret *at rest*
    against a server-side pepper. There is no canonical string to build, no
    `X-Signature` and no clock-skew window, so this class has no signing method
    and needs none.
    """

    __slots__ = ("prefix", "__secret")

    def __init__(self, raw: str) -> None:
        if not isinstance(raw, str) or not raw.strip():
            raise ConfigurationError("api_key is required and must be a non-empty string.")
        value = raw.strip()
        head, separator, tail = value.partition(_SEPARATOR)
        if not separator or not head or not tail:
            raise ConfigurationError(
                "api_key is not a GraphRec credential: it must be a prefix and a secret separated "
                'by a single "." — the whole value the console showed you once.'
            )
        if not head.startswith(PREFIX_NAMESPACE):
            raise ConfigurationError(
                f'api_key does not start with "{PREFIX_NAMESPACE}". Check you copied the '
                "credential from Credentials, not the key id or the visible prefix from the table."
            )
        #: `gr_live_XXXX`. Safe to log — it is how a person tells two apart.
        self.prefix = head
        self.__secret = value

    @property
    def authorization(self) -> str:
        """The `Authorization` value. The only member that can see the secret."""
        return f"Bearer {self.__secret}"

    def __str__(self) -> str:
        return f"{self.prefix}.[redacted]"

    def __repr__(self) -> str:
        return f"Credential({self})"

    def __reduce__(self) -> tuple[object, ...]:
        # `pickle` and `copy` both go through here, and both are ways a
        # credential ends up in a file or a cache nobody audited.
        raise TypeError("A Credential cannot be pickled or copied; construct it from the key.")
