from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class ComplianceStatus(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    NO_DATA = "NO_DATA"      # node silent, or its sensor reported ok=false

class NodeReading(BaseModel):
    node_id: str = Field(..., description="Node identifier, e.g. 'N01'")
    zone_id: str = Field(..., description="Parent zone identifier, e.g. 'Z1'")
    name: str = Field(..., description="Display name from site config, e.g. 'Sensor 1'")
    location: str = Field("", description="Where the node sits in the room, from site config")
    temp_c: Optional[float] = Field(None, description="Latest temperature in Celsius; None if no valid reading")
    humidity: Optional[float] = Field(None, description="Latest relative humidity percentage")
    status: ComplianceStatus = Field(ComplianceStatus.NO_DATA, description="Status against the zone limits")
    rate_c_per_hour: Optional[float] = Field(None, description="Temperature change over the last 30 min; None if offline or too little data")
    timestamp: Optional[datetime] = Field(None, description="UTC time of the latest report; None if never reported")

class LiveZoneReading(BaseModel):
    zone_id: str = Field(..., description="Zone identifier, e.g. 'Z1'")
    name: str = Field(..., description="Display name from site config")
    type: str = Field("", description="Room type from site config, e.g. 'Frozen storage'")
    limits: Optional[dict] = Field(None, description="Zone limits: min/max/warn_margin")
    temp_c: Optional[float] = Field(None, description="Mean temperature across reporting nodes")
    humidity: Optional[float] = Field(None, description="Mean humidity across reporting nodes")
    status: ComplianceStatus = Field(ComplianceStatus.NO_DATA, description="Worst node status in the zone")
    rate_c_per_hour: Optional[float] = Field(None, description="Mean of the reporting nodes' rates")
    timestamp: Optional[datetime] = Field(None, description="UTC time of the newest node report")
    nodes: List[NodeReading] = Field(default_factory=list, description="Every configured node in the zone")

class LiveZonesResponse(BaseModel):
    zones: List[LiveZoneReading]
    count: int
    server_time: datetime

class ZoneNodesResponse(BaseModel):
    zone_id: str
    nodes: List[NodeReading]
    count: int
    server_time: datetime

class TrendPoint(BaseModel):
    timestamp: datetime
    temp_c: Optional[float] = None
    humidity: Optional[float] = None

class ZoneTrendResponse(BaseModel):
    zone_id: str
    hours: int
    point_count: int
    data: List[TrendPoint]

class NodeTrendResponse(BaseModel):
    zone_id: str
    node_id: str
    hours: int
    point_count: int
    data: List[TrendPoint]
