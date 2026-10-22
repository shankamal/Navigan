"""Initialize the ephemeral mount, then drop privileges before worker imports."""
import os
if os.geteuid() == 0:
    os.chmod('/tmp', 0o1777)
    os.setgroups([])
    os.setgid(10001)
    os.setuid(10001)
from navigan.modules.migration_management.image_worker import main
main()
