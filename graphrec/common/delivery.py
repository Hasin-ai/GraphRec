"""Getting a one-time token to the person it was minted for.

There is no mail transport in this system. `docs/BUILD_PROMPT.md` L90 asks the
question directly and gives the answer for when the answer is no: *"If not,
build an admin CLI that prints the token and say so in your report."* This
module is where that decision lives, so that the day SMTP arrives it is one
function body that changes rather than a search through the routers.

Two tokens need out-of-band delivery, and they are handled differently because
the trust situations are different:

* An **invitation** is minted by an administrator who is already authenticated
  and who chose the recipient. Handing the token back in the HTTP response is
  defensible — `InvitationResponse.invitation_token` does exactly that, and says
  so in its docstring.
* A **recovery proof** is minted at the request of an unauthenticated stranger
  who typed an email address. Returning it in the response would make
  `POST /v1/auth/recovery` mean "reset anybody's password". So it must not be
  returned, and this module is the only other way out.

What `deliver_recovery` does is write the proof to a dedicated logger at
`WARNING`, with a banner saying plainly that a live credential is being
disclosed to the operator log. That is not good practice and it is not
pretending to be: it is a placeholder that is *loud*, so that nobody deploys it
by accident and nobody mistakes the log line for something ordinary. An operator
answering a support ticket has the alternative of `scripts/recovery_token.py`,
which mints a proof and prints it to a terminal without it passing through a log
file at all.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime as dt

#: Its own logger, so an installation can silence or divert this one stream
#: without touching the rest of the application's logging.
logger = logging.getLogger("graphrec.delivery")

BANNER = (
    "NO MAIL TRANSPORT IS CONFIGURED. A live recovery proof is being written to "
    "this log because there is nowhere else to send it. Configure delivery, or "
    "use scripts/recovery_token.py, before running this anywhere real."
)


def deliver_recovery(*, email: str, token: str, expires_at: dt.datetime) -> None:
    """Hand a recovery proof to the only transport that exists.

    Called only when a proof was actually minted. A request for an account that
    does not exist never reaches here, and never logs anything — a log line that
    appeared only for real accounts would be the disclosure the endpoint refuses
    to make, moved to a different file.
    """
    logger.warning(
        "%s recipient=%s proof=%s expires_at=%s",
        BANNER,
        email,
        token,
        expires_at.isoformat(),
    )


__all__ = ["BANNER", "deliver_recovery", "logger"]
