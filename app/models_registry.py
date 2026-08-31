"""Import every model module so they all register on Base.metadata —
used by Alembic's env.py for autogenerate. Import this module, not the
individual model modules, when you need the full metadata."""

from app.accounts import models as _accounts_models  # noqa: F401
from app.compliance import models as _compliance_models  # noqa: F401
from app.safety import models as _safety_models  # noqa: F401
from app.scans import models as _scans_models  # noqa: F401
from app.sites import models as _sites_models  # noqa: F401
from app.traceability import models as _traceability_models  # noqa: F401
from app.transport import models as _transport_models  # noqa: F401
from app.database import Base  # noqa: F401,E402
