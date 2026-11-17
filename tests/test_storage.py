from app.storage import is_persistent, mount_points

# Trimmed /proc/self/mountinfo of a container started with -v helpdesk-data:/data
WITH_VOLUME = """\
637 545 0:56 / / rw,relatime master:252 - overlay overlay rw,lowerdir=/var/lib/docker/...
638 637 0:59 / /proc rw,nosuid,nodev,noexec,relatime - proc proc rw
650 637 8:1 /var/lib/docker/volumes/helpdesk-data/_data /data rw,relatime - ext4 /dev/sda1 rw
651 637 8:1 /var/lib/docker/containers/abc/resolv.conf /etc/resolv.conf rw - ext4 /dev/sda1 rw
"""

# The same container started without a volume: /data is just a folder on the overlay root
WITHOUT_VOLUME = "\n".join(line for line in WITH_VOLUME.splitlines() if " /data " not in line)


def test_mount_points_parsed():
    assert {"/", "/proc", "/data", "/etc/resolv.conf"} == mount_points(WITH_VOLUME)


def test_mount_point_with_space_is_decoded():
    line = r"700 637 8:1 /x /mnt/my\040data rw - ext4 /dev/sda1 rw"
    assert "/mnt/my data" in mount_points(line)


def test_database_on_volume_is_persistent():
    assert is_persistent("/data/helpdesk.db", WITH_VOLUME)


def test_database_without_volume_is_not_persistent():
    # the overlay root "/" does not count: it is thrown away with the container
    assert not is_persistent("/data/helpdesk.db", WITHOUT_VOLUME)


def test_health_reports_storage(client):
    body = client.get("/health").json()
    assert body["version"] == "0.4.0"
    assert "persistent_storage" in body  # None on Windows/macOS, bool in Linux containers
