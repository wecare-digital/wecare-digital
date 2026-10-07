"""The refusals a Drop Docs document can earn, in a module both halves may depend on.

Why these live alone
--------------------
Two modules refuse a document, for different reasons and at different moments:
`dropdocs_storage` refuses while moving bytes, and `service_request_store.attach_document`
refuses while writing the row that makes those bytes a customer document. The store used to
import `dropdocs_storage` purely to borrow one exception class, which pointed the dependency
the wrong way round -- the single-table request store does not otherwise know that Drop Docs
has a storage step at all. Both now depend on this, and this depends on nothing.

Four refusals, because they mean four different things to a caller
------------------------------------------------------------------
The distinction is not taxonomy for its own sake. It decides what the HTTP layer says, and
"please try again" on a permanently invalid request is a lie that costs a support round
trip:

* `DocumentRejected` -- the input will never be acceptable. A malformed sha256, a byte count
  that is absent or negative, a source key outside the one allowed prefix, an object larger
  than the locker's own ceiling. Answered 400. Retrying is pointless.
* `DocumentPromotionFailed` -- S3 refused a read, a copy or the proving HEAD. Answered 503.
  Retrying is the right move.
* `DocumentNotPrivate` -- a key that is not under the gated root reached a point that
  requires one. Answered 503 **and alerted**, because reaching it means two independent
  checks disagreed about where an object lives.
* `DocumentLimitReached` -- the request already holds as many documents as it may. Answered
  409. A readable refusal, rather than the DynamoDB validation error that arrives when a
  400 KB item finally overflows.

Every one of them leaves the table untouched. There is no partial state in which a row
exists for an object still reachable under ``o/``.
"""

from __future__ import annotations

__all__ = [
    "DocumentLimitReached",
    "DocumentNotPrivate",
    "DocumentPromotionFailed",
    "DocumentRejected",
]


class DocumentRejected(ValueError):
    """The input is permanently invalid. Nothing was stored and nothing will be on retry."""


class DocumentPromotionFailed(RuntimeError):
    """S3 refused a read, a copy or the proving HEAD. No row may be written."""


class DocumentNotPrivate(RuntimeError):
    """A key that is not under the gated root reached a point that requires one.

    Raised rather than corrected. A key moved between roots to "make it work" is a
    disclosure in one direction and a dead link in the other.
    """


class DocumentLimitReached(RuntimeError):
    """The request already holds its maximum number of documents.

    A stated ceiling, refused readably, rather than letting the 400 KB DynamoDB item limit
    turn every further attach into an unreadable validation error.
    """
