"""Allow ``python -m dataguard.validation`` from the repository environment."""

from dataguard.validation.cli import main


raise SystemExit(main())

