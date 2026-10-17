# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GTK 4 + libadwaita interface."""

from .. import winsupport

# On Windows the GTK runtime has to be made visible before ``gi`` is imported by any submodule.
winsupport.prepare_runtime()
