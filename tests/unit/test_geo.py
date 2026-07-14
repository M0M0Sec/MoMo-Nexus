"""
Tests for GPS and geofencing.
"""

from datetime import datetime, timedelta

import pytest

from nexus.geo.location import (
    GPSCoordinate,
    Location,
    LocationFix,
    bearing,
    bounding_box,
    destination_point,
    distance_haversine,
    format_bearing,
    format_distance,
    midpoint,
)
from nexus.geo.manager import GeoManager, ZoneEvent, ZoneEventType
from nexus.geo.tracker import LocationTracker, TrackPoint
from nexus.geo.zones import (
    CircleZone,
    PolygonZone,
    RectangleZone,
    Zone,
    ZoneType,
)


class TestGPSCoordinate:
    """Tests for GPS coordinate operations."""

    def test_create_coordinate(self) -> None:
        """Test coordinate creation."""
        coord = GPSCoordinate(lat=40.7128, lon=-74.0060)
        assert coord.lat == 40.7128
        assert coord.lon == -74.0060

    def test_invalid_latitude(self) -> None:
        """Test invalid latitude rejection."""
        with pytest.raises(ValueError):
            GPSCoordinate(lat=91, lon=0)

    def test_invalid_longitude(self) -> None:
        """Test invalid longitude rejection."""
        with pytest.raises(ValueError):
            GPSCoordinate(lat=0, lon=181)

    def test_to_tuple(self) -> None:
        """Test tuple conversion."""
        coord = GPSCoordinate(lat=40.0, lon=-74.0)
        assert coord.to_tuple() == (40.0, -74.0)

    def test_from_tuple(self) -> None:
        """Test creation from tuple."""
        coord = GPSCoordinate.from_tuple((40.0, -74.0))
        assert coord.lat == 40.0
        assert coord.lon == -74.0

    def test_to_dict(self) -> None:
        """Test dictionary conversion."""
        coord = GPSCoordinate(lat=40.0, lon=-74.0)
        d = coord.to_dict()
        assert d["lat"] == 40.0
        assert d["lon"] == -74.0


class TestDistanceCalculations:
    """Tests for distance and bearing calculations."""

    def test_distance_haversine_same_point(self) -> None:
        """Test distance to same point is zero."""
        p = GPSCoordinate(lat=40.0, lon=-74.0)
        assert distance_haversine(p, p) == 0

    def test_distance_haversine_known_distance(self) -> None:
        """Test distance against known value."""
        # New York to Los Angeles (approximately 3944 km)
        nyc = GPSCoordinate(lat=40.7128, lon=-74.0060)
        la = GPSCoordinate(lat=34.0522, lon=-118.2437)

        dist = distance_haversine(nyc, la)

        # Allow 1% error
        assert 3900000 < dist < 4000000

    def test_bearing_north(self) -> None:
        """Test bearing due north."""
        p1 = GPSCoordinate(lat=0, lon=0)
        p2 = GPSCoordinate(lat=1, lon=0)

        b = bearing(p1, p2)
        assert abs(b - 0) < 1  # Should be ~0 degrees

    def test_bearing_east(self) -> None:
        """Test bearing due east."""
        p1 = GPSCoordinate(lat=0, lon=0)
        p2 = GPSCoordinate(lat=0, lon=1)

        b = bearing(p1, p2)
        assert abs(b - 90) < 1  # Should be ~90 degrees

    def test_destination_point(self) -> None:
        """Test destination point calculation."""
        start = GPSCoordinate(lat=0, lon=0)
        dist = 111320  # ~1 degree at equator

        # Go north
        dest = destination_point(start, dist, 0)
        assert abs(dest.lat - 1.0) < 0.01

        # Go east
        dest = destination_point(start, dist, 90)
        assert abs(dest.lon - 1.0) < 0.01

    def test_midpoint(self) -> None:
        """Test midpoint calculation."""
        p1 = GPSCoordinate(lat=0, lon=0)
        p2 = GPSCoordinate(lat=2, lon=2)

        mid = midpoint(p1, p2)
        assert abs(mid.lat - 1.0) < 0.1
        assert abs(mid.lon - 1.0) < 0.1

    def test_bounding_box(self) -> None:
        """Test bounding box calculation."""
        center = GPSCoordinate(lat=40.0, lon=-74.0)
        radius = 1000  # 1km

        sw, ne = bounding_box(center, radius)

        assert sw.lat < center.lat < ne.lat
        assert sw.lon < center.lon < ne.lon


class TestFormatting:
    """Tests for formatting functions."""

    def test_format_distance_meters(self) -> None:
        """Test distance formatting in meters."""
        assert format_distance(500) == "500m"

    def test_format_distance_kilometers(self) -> None:
        """Test distance formatting in kilometers."""
        assert format_distance(2500) == "2.50km"

    def test_format_bearing(self) -> None:
        """Test bearing formatting."""
        assert format_bearing(0) == "N"
        assert format_bearing(90) == "E"
        assert format_bearing(180) == "S"
        assert format_bearing(270) == "W"
        assert format_bearing(45) == "NE"


class TestCircleZone:
    """Tests for circle zones."""

    def test_create_circle(self) -> None:
        """Test circle creation."""
        center = GPSCoordinate(lat=40.0, lon=-74.0)
        zone = CircleZone(
            id="test-1",
            name="Test Circle",
            center=center,
            radius=100,
        )

        assert zone.zone_type == ZoneType.CIRCLE
        assert zone.radius == 100

    def test_contains_center(self) -> None:
        """Test that center is inside."""
        center = GPSCoordinate(lat=40.0, lon=-74.0)
        zone = CircleZone(id="z1", name="Test", center=center, radius=100)

        assert zone.contains(center) is True

    def test_contains_edge(self) -> None:
        """Test point near edge."""
        center = GPSCoordinate(lat=40.0, lon=-74.0)
        zone = CircleZone(id="z1", name="Test", center=center, radius=1000)

        # Point 500m north (should be inside)
        inside = destination_point(center, 500, 0)
        assert zone.contains(inside) is True

        # Point 1500m north (should be outside)
        outside = destination_point(center, 1500, 0)
        assert zone.contains(outside) is False

    def test_distance_to_boundary(self) -> None:
        """Test distance to boundary."""
        center = GPSCoordinate(lat=40.0, lon=-74.0)
        zone = CircleZone(id="z1", name="Test", center=center, radius=1000)

        # At center, should be -1000m (inside)
        assert abs(zone.distance_to_boundary(center) + 1000) < 10

        # 2000m away, should be +1000m (outside)
        far = destination_point(center, 2000, 0)
        assert abs(zone.distance_to_boundary(far) - 1000) < 10


class TestPolygonZone:
    """Tests for polygon zones."""

    def test_create_polygon(self) -> None:
        """Test polygon creation."""
        vertices = [
            GPSCoordinate(0, 0),
            GPSCoordinate(0, 1),
            GPSCoordinate(1, 1),
            GPSCoordinate(1, 0),
        ]
        zone = PolygonZone(id="p1", name="Square", vertices=vertices)

        assert zone.zone_type == ZoneType.POLYGON
        assert len(zone.vertices) == 4

    def test_polygon_too_few_vertices(self) -> None:
        """Test that polygon requires 3+ vertices."""
        with pytest.raises(ValueError):
            PolygonZone(
                id="p1",
                name="Invalid",
                vertices=[GPSCoordinate(0, 0), GPSCoordinate(1, 1)],
            )

    def test_contains_point(self) -> None:
        """Test point containment."""
        vertices = [
            GPSCoordinate(0, 0),
            GPSCoordinate(0, 2),
            GPSCoordinate(2, 2),
            GPSCoordinate(2, 0),
        ]
        zone = PolygonZone(id="p1", name="Square", vertices=vertices)

        # Point inside
        assert zone.contains(GPSCoordinate(1, 1)) is True

        # Point outside
        assert zone.contains(GPSCoordinate(3, 3)) is False

    def test_centroid(self) -> None:
        """Test centroid calculation."""
        vertices = [
            GPSCoordinate(0, 0),
            GPSCoordinate(0, 2),
            GPSCoordinate(2, 2),
            GPSCoordinate(2, 0),
        ]
        zone = PolygonZone(id="p1", name="Square", vertices=vertices)

        centroid = zone.centroid
        assert abs(centroid.lat - 1.0) < 0.01
        assert abs(centroid.lon - 1.0) < 0.01


class TestRectangleZone:
    """Tests for rectangle zones."""

    def test_create_rectangle(self) -> None:
        """Test rectangle creation."""
        zone = RectangleZone(
            id="r1",
            name="Test Rect",
            southwest=GPSCoordinate(0, 0),
            northeast=GPSCoordinate(1, 1),
        )

        assert zone.zone_type == ZoneType.RECTANGLE

    def test_contains_point(self) -> None:
        """Test point containment."""
        zone = RectangleZone(
            id="r1",
            name="Test",
            southwest=GPSCoordinate(0, 0),
            northeast=GPSCoordinate(2, 2),
        )

        assert zone.contains(GPSCoordinate(1, 1)) is True
        assert zone.contains(GPSCoordinate(3, 3)) is False

    def test_center(self) -> None:
        """Test center calculation."""
        zone = RectangleZone(
            id="r1",
            name="Test",
            southwest=GPSCoordinate(0, 0),
            northeast=GPSCoordinate(2, 2),
        )

        center = zone.center
        assert center.lat == 1.0
        assert center.lon == 1.0


class TestLocationTracker:
    """Tests for location tracker."""

    @pytest.fixture
    def tracker(self) -> LocationTracker:
        """Create tracker."""
        return LocationTracker(
            max_history_per_device=100,
            min_distance=0,  # No filtering for tests
        )

    @pytest.mark.asyncio
    async def test_update_location(self, tracker: LocationTracker) -> None:
        """Test location update."""
        location = Location(lat=40.0, lon=-74.0)
        point = await tracker.update("dev-1", location)

        assert point is not None
        assert point.device_id == "dev-1"

    @pytest.mark.asyncio
    async def test_get_current(self, tracker: LocationTracker) -> None:
        """Test getting current location."""
        await tracker.update("dev-1", Location(40.0, -74.0))

        current = await tracker.get_current("dev-1")
        assert current is not None
        assert current.location.lat == 40.0

    @pytest.mark.asyncio
    async def test_history(self, tracker: LocationTracker) -> None:
        """Test location history."""
        await tracker.update("dev-1", Location(40.0, -74.0))
        await tracker.update("dev-1", Location(40.1, -74.0))
        await tracker.update("dev-1", Location(40.2, -74.0))

        history = await tracker.get_history("dev-1")
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_distance_filtering(self) -> None:
        """Test minimum distance filtering."""
        tracker = LocationTracker(min_distance=100)  # 100m minimum

        await tracker.update("dev-1", Location(40.0, -74.0))
        # This should be filtered (too close)
        result = await tracker.update("dev-1", Location(40.0, -74.0))

        assert result is None

    @pytest.mark.asyncio
    async def test_nearby_devices(self, tracker: LocationTracker) -> None:
        """Test finding nearby devices."""
        await tracker.update("dev-1", Location(40.0, -74.0))
        await tracker.update("dev-2", Location(40.001, -74.0))  # ~111m away
        await tracker.update("dev-3", Location(41.0, -74.0))  # ~111km away

        nearby = await tracker.get_nearby_devices(
            GPSCoordinate(40.0, -74.0),
            radius=1000,  # 1km
        )

        # Should find dev-1 and dev-2
        device_ids = [d[0] for d in nearby]
        assert "dev-1" in device_ids
        assert "dev-2" in device_ids
        assert "dev-3" not in device_ids


class TestGeoManager:
    """Tests for geo manager."""

    @pytest.fixture
    def manager(self) -> GeoManager:
        """Create geo manager."""
        from nexus.config import NexusConfig
        config = NexusConfig()
        return GeoManager(config=config)

    @pytest.mark.asyncio
    async def test_add_zone(self, manager: GeoManager) -> None:
        """Test adding a zone."""
        zone = CircleZone(
            id="z1",
            name="Test Zone",
            center=GPSCoordinate(40.0, -74.0),
            radius=100,
        )

        await manager.add_zone(zone)

        retrieved = await manager.get_zone("z1")
        assert retrieved is not None
        assert retrieved.name == "Test Zone"

    @pytest.mark.asyncio
    async def test_zone_enter_event(self, manager: GeoManager) -> None:
        """Test zone enter event."""
        zone = CircleZone(
            id="z1",
            name="Test Zone",
            center=GPSCoordinate(40.0, -74.0),
            radius=1000,
        )
        await manager.add_zone(zone)

        # Device outside zone
        await manager.update_location("dev-1", Location(41.0, -74.0))

        # Device enters zone
        events = await manager.update_location("dev-1", Location(40.0, -74.0))

        assert len(events) == 1
        assert events[0].event_type == ZoneEventType.ENTER

    @pytest.mark.asyncio
    async def test_zone_exit_event(self, manager: GeoManager) -> None:
        """Test zone exit event."""
        zone = CircleZone(
            id="z1",
            name="Test Zone",
            center=GPSCoordinate(40.0, -74.0),
            radius=1000,
        )
        await manager.add_zone(zone)

        # Device inside zone
        await manager.update_location("dev-1", Location(40.0, -74.0))

        # Device exits zone
        events = await manager.update_location("dev-1", Location(41.0, -74.0))

        assert len(events) == 1
        assert events[0].event_type == ZoneEventType.EXIT

    @pytest.mark.asyncio
    async def test_get_devices_in_zone(self, manager: GeoManager) -> None:
        """Test getting devices in a zone."""
        zone = CircleZone(
            id="z1",
            name="Test Zone",
            center=GPSCoordinate(40.0, -74.0),
            radius=1000,
        )
        await manager.add_zone(zone)

        # Place device in zone
        await manager.update_location("dev-1", Location(40.0, -74.0))

        devices = await manager.get_devices_in_zone("z1")
        assert "dev-1" in devices

